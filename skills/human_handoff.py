"""Human-handoff Skill backed by a locally persisted Mock ticket."""

from __future__ import annotations

from app.schemas.api import ChatError, ChatStatus, HandoffInfo, TraceEvent
from skills.base import SkillContext, SkillResult
from tools.protocols import ToolFailure


class HumanHandoffSkill:
    skill_id = "human_handoff"

    def execute(self, context: SkillContext, *, order_id: str | None) -> SkillResult:
        del order_id
        if not context.tool_budget.claim():
            return SkillResult(
                answer="本次会话达到工具调用上限，无法创建模拟人工工单。请稍后重试。",
                status=ChatStatus.FAILED,
                state=context.state,
                trace=[
                    TraceEvent(
                        step=1,
                        action="tool_step_budget",
                        status="failed",
                        summary="已达到商家配置的最大工具步数。",
                        error_code="TOOL_STEP_LIMIT",
                    )
                ],
                error=ChatError(code="TOOL_STEP_LIMIT", message="无法创建模拟人工工单。"),
            )
        reason = context.handoff_reason or "客户明确要求人工客服"
        try:
            ticket = context.tools.handoff.create_ticket(
                session_id=context.session_id,
                summary=context.conversation_summary,
                reason=reason,
            )
        except ToolFailure as exc:
            return _handoff_failure(context, exc.code, exc.safe_message)
        except Exception:
            return _handoff_failure(context, "TOOL_ERROR", "模拟人工工单创建失败。")
        handoff = HandoffInfo(ticket_id=ticket.ticket_id, status=ticket.status, created_at=ticket.created_at)
        return SkillResult(
            answer=(
                f"已创建模拟人工工单 {ticket.ticket_id}。原因：{reason}。"
                "该工单未连接真实人工客服，也不会产生实际业务处理。"
            ),
            status=ChatStatus.HANDED_OFF,
            state=context.state,
            handoff=handoff,
            trace=[
                TraceEvent(
                    step=1,
                    action="mock_handoff.create_ticket",
                    status="success",
                    summary="已创建模拟人工工单。",
                )
            ],
        )


def _handoff_failure(context: SkillContext, code: str, message: str) -> SkillResult:
    return SkillResult(
        answer=message,
        status=ChatStatus.FAILED,
        state=context.state,
        trace=[
            TraceEvent(
                step=1,
                action="mock_handoff.create_ticket",
                status="failed",
                summary="模拟人工工单创建失败。",
                error_code=code,
            )
        ],
        error=ChatError(code=code, message=message),
    )
