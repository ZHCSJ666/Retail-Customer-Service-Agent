"""Deterministic refund-application eligibility Skill; it never performs a refund."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.contracts import IntentName
from app.schemas.api import ChatError, ChatStatus, TraceEvent
from skills.base import SkillContext, SkillResult
from tools.protocols import OrderLookupStatus, ToolFailure


class RefundEligibilitySkill:
    skill_id = "refund_eligibility"

    def execute(self, context: SkillContext, *, order_id: str | None) -> SkillResult:
        if not order_id:
            next_state = context.state.model_copy(
                update={
                    "awaiting_order_id": True,
                    "pending_order_skill": IntentName.REFUND_ELIGIBILITY,
                    "order_lookup_prompt_count": min(context.state.order_lookup_prompt_count + 1, 3),
                }
            )
            return SkillResult(
                answer="请提供需要判断退款资格的订单号，格式如 SS-2026-10001。此判断不会执行退款。",
                status=ChatStatus.NEEDS_INFO,
                state=next_state,
                trace=[
                    TraceEvent(
                        step=1,
                        action="refund_eligibility",
                        status="skipped",
                        summary="缺少订单号，已发起追问。",
                    )
                ],
            )
        if not context.tool_budget.claim():
            return _failed(context, "TOOL_STEP_LIMIT", "本次会话达到最大工具调用步数。")
        try:
            lookup = context.tools.order.lookup_for_customer(
                customer_id=context.customer_id, order_id=order_id
            )
        except ToolFailure as exc:
            return _failed(context, exc.code, exc.safe_message, increment_failure=True)
        except Exception:
            return _failed(context, "TOOL_ERROR", "业务查询暂时不可用。", increment_failure=True)

        clear_state = context.state.model_copy(
            update={
                "awaiting_order_id": False,
                "pending_order_skill": None,
                "order_lookup_prompt_count": 0,
                "consecutive_tool_failures": 0,
            }
        )
        if lookup.status == OrderLookupStatus.NOT_FOUND:
            return SkillResult(
                answer=f"未找到订单 {order_id}，无法判断退款申请资格。请核对订单号。",
                status=ChatStatus.COMPLETED,
                state=clear_state,
                trace=[_order_trace("订单工具已完成查询，未找到匹配订单。")],
            )
        if lookup.status == OrderLookupStatus.FORBIDDEN:
            return SkillResult(
                answer="无法判断该订单的退款资格。请确认订单号属于当前选择的模拟客户。",
                status=ChatStatus.COMPLETED,
                state=clear_state,
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
        if order is None:
            return _failed(context, "TOOL_ERROR", "业务查询暂时不可用。", increment_failure=True)
        decision, reason = _evaluate(order.status, order.delivered_at, context.merchant.config.refund_rules)
        label = {"eligible": "可申请", "ineligible": "不可申请", "needs_info": "信息不足"}[decision]
        return SkillResult(
            answer=(
                f"订单 {order.order_id} 的退款申请资格：{label}。原因：{reason}。"
                f"适用规则版本：{context.merchant.config.refund_rules.version}。"
                "这只是资格判断，不会执行退款、取消订单或原路退回。"
            ),
            status=ChatStatus.COMPLETED if decision != "needs_info" else ChatStatus.NEEDS_INFO,
            state=clear_state,
            trace=[
                _order_trace("订单归属校验通过并返回订单状态。"),
                TraceEvent(
                    step=1,
                    action="deterministic_refund_rules.evaluate",
                    status="success",
                    summary=f"按规则版本 {context.merchant.config.refund_rules.version} 得出：{decision}。",
                ),
            ],
        )


def _evaluate(status: str, delivered_at: str | None, rules: object) -> tuple[str, str]:
    # The caller passes RefundRulesConfig; duck typing keeps this function easily
    # reusable by a future merchant-specific rules adapter.
    if status == "pending_shipment":
        if rules.unshipped_order_eligible:
            return "eligible", "订单尚未发货，符合未发货订单的申请规则"
        return "ineligible", "商家规则未允许未发货订单申请退款"
    if status == "cancelled":
        if rules.cancelled_order_eligible:
            return "eligible", "商家规则允许已取消订单申请退款"
        return "ineligible", "订单已取消，商家规则不允许再次申请退款"
    if status == "delivered":
        if not delivered_at:
            return "needs_info", "订单缺少签收时间，无法核验退货申请窗口"
        delivered_date = datetime.fromisoformat(delivered_at.replace("Z", "+00:00")).date()
        deadline = delivered_date + timedelta(days=rules.delivered_return_window_days)
        today = datetime.now(timezone.utc).date()
        if today <= deadline:
            return "eligible", f"签收日期在 {rules.delivered_return_window_days} 天申请窗口内"
        return "ineligible", f"已超过签收后 {rules.delivered_return_window_days} 天申请窗口"
    return "needs_info", "当前订单状态没有匹配的退款资格规则，需要人工确认"


def _order_trace(summary: str) -> TraceEvent:
    return TraceEvent(step=1, action="mock_order.lookup", status="success", summary=summary)


def _failed(context: SkillContext, code: str, message: str, increment_failure: bool = False) -> SkillResult:
    next_state = context.state
    if increment_failure:
        next_state = context.state.model_copy(
            update={"consecutive_tool_failures": min(context.state.consecutive_tool_failures + 1, 10)}
        )
    return SkillResult(
        answer=message,
        status=ChatStatus.FAILED,
        state=next_state,
        trace=[
            TraceEvent(
                step=1,
                action="business_tool",
                status="failed",
                summary="订单工具调用失败，未返回虚构退款资格。",
                error_code=code,
            )
        ],
        error=ChatError(code=code, message=message),
    )
