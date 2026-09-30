"""Order lookup Skill using only trusted session identity and tool contracts."""

from __future__ import annotations

from agent.contracts import IntentName
from app.schemas.api import ChatError, ChatStatus, TraceEvent
from skills.base import SkillContext, SkillResult
from tools.protocols import OrderLookupStatus, ToolFailure


STATUS_LABELS = {
    "pending_shipment": "待发货",
    "in_transit": "运输中",
    "delivered": "已签收",
    "cancelled": "已取消",
}


class OrderLookupSkill:
    skill_id = "order_lookup"

    def execute(self, context: SkillContext, *, order_id: str | None) -> SkillResult:
        if not order_id:
            next_state = context.state.model_copy(
                update={
                    "awaiting_order_id": True,
                    "pending_order_skill": IntentName.ORDER_LOOKUP,
                    "order_lookup_prompt_count": min(context.state.order_lookup_prompt_count + 1, 3),
                }
            )
            return SkillResult(
                answer="请提供要查询的订单号，格式如 SS-2026-10001。",
                status=ChatStatus.NEEDS_INFO,
                state=next_state,
                trace=[
                    TraceEvent(
                        step=1,
                        action="order_lookup",
                        status="skipped",
                        summary="缺少订单号，已发起追问。",
                    )
                ],
            )

        if not context.tool_budget.claim():
            return _tool_step_limit(context)

        try:
            lookup = context.tools.order.lookup_for_customer(
                customer_id=context.customer_id,
                order_id=order_id,
            )
        except ToolFailure as exc:
            return _tool_failure(context, exc)
        except Exception:
            return _tool_failure(context, ToolFailure("Unexpected order tool failure"))

        cleared_state = context.state.model_copy(
            update={
                "awaiting_order_id": False,
                "pending_order_skill": None,
                "order_lookup_prompt_count": 0,
                "consecutive_tool_failures": 0,
            }
        )
        if lookup.status == OrderLookupStatus.NOT_FOUND:
            return SkillResult(
                answer=f"未找到订单 {order_id}。请核对订单号后再试。",
                status=ChatStatus.COMPLETED,
                state=cleared_state,
                trace=[
                    TraceEvent(
                        step=1,
                        action="mock_order.lookup",
                        status="success",
                        summary="订单工具已完成查询，未找到匹配订单。",
                    )
                ],
            )
        if lookup.status == OrderLookupStatus.FORBIDDEN:
            return SkillResult(
                answer="无法查询该订单。请确认订单号属于当前选择的模拟客户。",
                status=ChatStatus.COMPLETED,
                state=cleared_state,
                trace=[
                    TraceEvent(
                        step=1,
                        action="mock_order.ownership_check",
                        status="failed",
                        summary="订单归属校验未通过；未返回订单详情。",
                        error_code="ORDER_ACCESS_DENIED",
                    )
                ],
            )

        order = lookup.order
        if order is None:  # Defensive guard for an adapter violating its contract.
            return _tool_failure(context, ToolFailure("Found result without order payload"))
        traces = [
            TraceEvent(
                step=1,
                action="mock_order.lookup",
                status="success",
                summary="订单归属校验通过并返回订单状态。",
            )
        ]
        if not context.tool_budget.claim():
            return _tool_step_limit(context, traces=traces)
        try:
            shipping = context.tools.shipping.lookup_for_authorized_order(order=order)
        except ToolFailure as exc:
            return _tool_failure(context, exc, traces=traces)
        except Exception:
            return _tool_failure(context, ToolFailure("Unexpected shipping tool failure"), traces=traces)

        traces.append(
            TraceEvent(
                step=1,
                action="mock_shipping.lookup",
                status="success",
                summary=f"物流工具返回：{shipping.availability}。",
            )
        )
        item_names = "、".join(f"{item.product_name} × {item.quantity}" for item in order.items)
        answer = (
            f"订单 {order.order_id} 当前状态：{STATUS_LABELS.get(order.status, order.status)}。"
            f"商品：{item_names}。"
        )
        if shipping.availability == "available":
            answer += f"物流：{shipping.carrier}，运单号 {shipping.tracking_number}，状态 {shipping.status}。"
            if shipping.estimated_delivery_at:
                answer += f"预计送达时间：{shipping.estimated_delivery_at}。"
        elif shipping.availability == "unknown":
            answer += "物流信息暂缺，暂时无法确认运输进度或预计送达时间。"
        else:
            answer += "该订单当前没有可查询的物流信息。"
        return SkillResult(answer=answer, status=ChatStatus.COMPLETED, state=cleared_state, trace=traces)


def _tool_step_limit(context: SkillContext, traces: list[TraceEvent] | None = None) -> SkillResult:
    return SkillResult(
        answer="本次查询达到工具调用上限，未能安全完成订单查询。请稍后重试。",
        status=ChatStatus.FAILED,
        state=context.state,
        trace=(traces or [])
        + [
            TraceEvent(
                step=1,
                action="tool_step_budget",
                status="failed",
                summary="已达到商家配置的最大工具步数。",
                error_code="TOOL_STEP_LIMIT",
            )
        ],
        error=ChatError(code="TOOL_STEP_LIMIT", message="本次会话达到最大工具调用步数。"),
    )


def _tool_failure(
    context: SkillContext, exc: ToolFailure, traces: list[TraceEvent] | None = None
) -> SkillResult:
    next_state = context.state.model_copy(
        update={"consecutive_tool_failures": min(context.state.consecutive_tool_failures + 1, 10)}
    )
    return SkillResult(
        answer=exc.safe_message,
        status=ChatStatus.FAILED,
        state=next_state,
        trace=(traces or [])
        + [
            TraceEvent(
                step=1,
                action="business_tool",
                status="failed",
                summary="订单或物流工具调用失败，未返回虚构结果。",
                error_code=exc.code,
            )
        ],
        error=ChatError(code=exc.code, message=exc.safe_message),
    )
