"""Bounded execution of structured intents through registered Skills."""

from __future__ import annotations

from pydantic import ValidationError

from app.core.config import MerchantCatalog
from app.core.database import SessionStore
from app.demo_data.repository import DemoDataRepository
from app.schemas.api import ChatError, ChatResponse, ChatStatus, Citation, IntentResponse, TraceEvent
from agent.contracts import ConversationState, IntentName
from agent.model_adapter import ModelAdapterError, StructuredIntentModel
from rag.retrieve import LocalRetriever
from skills.base import SkillContext, ToolStepBudget
from skills.registry import SkillRegistry
from tools.registry import ToolAdapterRegistry


class AgentOrchestrator:
    """Routes bounded, validated intent plans; it never executes model-generated code."""

    def __init__(
        self,
        *,
        sessions: SessionStore,
        merchants: MerchantCatalog,
        demo_data: DemoDataRepository,
        retriever: LocalRetriever,
        intent_model: StructuredIntentModel,
        registry: SkillRegistry,
        tool_adapters: ToolAdapterRegistry,
    ) -> None:
        self.sessions = sessions
        self.merchants = merchants
        self.demo_data = demo_data
        self.retriever = retriever
        self.intent_model = intent_model
        self.registry = registry
        self.tool_adapters = tool_adapters

    @property
    def active_skill_ids(self) -> set[str]:
        return self.registry.active_ids()

    def respond(self, *, session_id: str, message: str) -> ChatResponse:
        session = self.sessions.get_session(session_id)
        if session is None:
            raise KeyError(session_id)
        clean_message = message.strip()
        self.sessions.append_message(session_id, "user", clean_message)

        merchant = self.merchants.get(session["merchant_id"])
        try:
            conversation_state = ConversationState.model_validate(self.sessions.get_state(session_id))
        except Exception:
            # Corrupt local state must not cause an unbounded or unsafe workflow.
            conversation_state = ConversationState()
        history = self.sessions.list_messages(session_id)[-merchant.config.agent.max_history_messages :]
        try:
            plan = self.intent_model.extract_intents(
                message=clean_message,
                history=history,
                state=conversation_state,
                order_id_pattern=merchant.config.order_id_pattern,
            )
        except (ModelAdapterError, ValidationError, ValueError, TypeError):
            return self._model_failure(session_id, conversation_state)

        traces: list[TraceEvent] = [
            TraceEvent(
                step=1,
                action="intent_extraction",
                status="success",
                summary=f"已识别 {len(plan.intents)} 个意图。",
            )
        ]
        answers: list[str] = []
        used_skills: list[str] = []
        result_states: list[ChatStatus] = []
        result_error: ChatError | None = None
        tool_budget = ToolStepBudget(merchant.config.agent.max_tool_steps)
        tools = self.tool_adapters.build_toolset(
            merchant=merchant, demo_data=self.demo_data, sessions=self.sessions
        )
        current_state = conversation_state
        sources = []
        handoff = None
        conversation_summary = _conversation_summary(history)

        for intent in plan.intents:
            skill_id = intent.intent.value
            if intent.intent == IntentName.UNKNOWN:
                answers.append("请说明您想查询的订单、物流、商品政策、退款资格或人工客服事项。")
                result_states.append(ChatStatus.NEEDS_INFO)
                traces.append(
                    TraceEvent(
                        step=1,
                        action="skill_router",
                        status="skipped",
                        summary="未匹配可执行的客服意图。",
                    )
                )
                continue
            if skill_id not in merchant.config.enabled_skills:
                answers.append(f"当前商家未启用 {skill_id} 能力，无法处理该部分请求。")
                result_states.append(ChatStatus.FAILED)
                result_error = ChatError(code="SKILL_DISABLED", message="请求的 Skill 未在当前商家启用。")
                traces.append(
                    TraceEvent(
                        step=1,
                        action="skill_router",
                        status="skipped",
                        summary=f"{skill_id} 未在商家配置中启用。",
                        error_code="SKILL_DISABLED",
                    )
                )
                continue
            skill = self.registry.get(skill_id)
            if skill is None:
                answers.append(f"{skill_id} 已在商家配置中声明，但本版本尚未实现，未执行任何业务操作。")
                result_states.append(ChatStatus.FAILED)
                result_error = ChatError(code="SKILL_NOT_IMPLEMENTED", message="请求的 Skill 尚未实现。")
                traces.append(
                    TraceEvent(
                        step=1,
                        action="skill_router",
                        status="skipped",
                        summary=f"{skill_id} 尚未注册为可执行 Skill。",
                        error_code="SKILL_NOT_IMPLEMENTED",
                    )
                )
                continue

            traces.append(
                TraceEvent(
                    step=1,
                    action="skill_router",
                    status="success",
                    summary=f"已路由至 {skill_id}。",
                )
            )
            result = skill.execute(
                SkillContext(
                    merchant=merchant,
                    session_id=session_id,
                    customer_id=session["customer_id"],
                    tools=tools,
                    state=current_state,
                    tool_budget=tool_budget,
                    retriever=self.retriever,
                    message=clean_message,
                    conversation_summary=conversation_summary,
                ),
                order_id=intent.order_id,
            )
            answers.append(result.answer)
            used_skills.append(skill_id)
            result_states.append(result.status)
            traces.extend(result.trace)
            sources.extend(result.sources)
            current_state = result.state
            if result.handoff is not None:
                handoff = result.handoff
            if result.error is not None:
                result_error = result.error

            escalation_reason = _automatic_handoff_reason(result.status, current_state)
            handoff_skill = self.registry.get(IntentName.HUMAN_HANDOFF.value)
            if escalation_reason and skill_id != IntentName.HUMAN_HANDOFF.value and handoff_skill is not None:
                traces.append(
                    TraceEvent(
                        step=1,
                        action="handoff_policy",
                        status="success",
                        summary="达到自动人工升级条件。",
                    )
                )
                handoff_result = handoff_skill.execute(
                    SkillContext(
                        merchant=merchant,
                        session_id=session_id,
                        customer_id=session["customer_id"],
                        tools=tools,
                        state=current_state,
                        tool_budget=tool_budget,
                        retriever=self.retriever,
                        message=clean_message,
                        conversation_summary=conversation_summary,
                        handoff_reason=escalation_reason,
                    ),
                    order_id=None,
                )
                answers.append(handoff_result.answer)
                used_skills.append(IntentName.HUMAN_HANDOFF.value)
                result_states.append(handoff_result.status)
                traces.extend(handoff_result.trace)
                sources.extend(handoff_result.sources)
                current_state = handoff_result.state
                if handoff_result.handoff is not None:
                    handoff = handoff_result.handoff
                if handoff_result.error is not None:
                    result_error = handoff_result.error

        self.sessions.set_state(session_id, current_state.model_dump(mode="json"))
        final_status = _combine_statuses(result_states)
        # A partial multi-intent result must not be marked globally failed if at
        # least one requested operation completed. The skipped action remains in trace.
        if final_status != ChatStatus.FAILED:
            result_error = None
        response = ChatResponse(
            session_id=session_id,
            answer="\n\n".join(answers),
            status=final_status,
            intents=[
                IntentResponse(
                    intent=intent.intent.value, order_id=intent.order_id, rationale=intent.rationale
                )
                for intent in plan.intents
            ],
            used_skills=used_skills,
            sources=_deduplicate_sources(sources),
            trace=_number_traces(traces),
            handoff=handoff,
            error=result_error if final_status == ChatStatus.FAILED else None,
        )
        self.sessions.append_message(session_id, "assistant", response.answer)
        return response

    def _model_failure(self, session_id: str, state: ConversationState) -> ChatResponse:
        self.sessions.set_state(session_id, state.model_dump(mode="json"))
        response = ChatResponse(
            session_id=session_id,
            answer="意图识别服务暂时不可用，本次没有调用订单、物流或其他业务工具。请稍后重试。",
            status=ChatStatus.FAILED,
            intents=[],
            used_skills=[],
            sources=[],
            trace=[
                TraceEvent(
                    step=1,
                    action="intent_extraction",
                    status="failed",
                    summary="模型适配器未返回可验证的意图计划。",
                    error_code="MODEL_UNAVAILABLE",
                )
            ],
            handoff=None,
            error=ChatError(code="MODEL_UNAVAILABLE", message="意图识别服务暂时不可用。"),
        )
        self.sessions.append_message(session_id, "assistant", response.answer)
        return response


def _number_traces(events: list[TraceEvent]) -> list[TraceEvent]:
    return [event.model_copy(update={"step": index}) for index, event in enumerate(events, start=1)]


def _combine_statuses(statuses: list[ChatStatus]) -> ChatStatus:
    if not statuses:
        return ChatStatus.FAILED
    if ChatStatus.HANDED_OFF in statuses:
        return ChatStatus.HANDED_OFF
    if ChatStatus.COMPLETED in statuses:
        return ChatStatus.COMPLETED
    if ChatStatus.NEEDS_INFO in statuses:
        return ChatStatus.NEEDS_INFO
    return ChatStatus.FAILED


def _automatic_handoff_reason(status: ChatStatus, state: ConversationState) -> str | None:
    if status == ChatStatus.NEEDS_INFO and state.order_lookup_prompt_count >= 3:
        return "多次补充后仍缺少可查询的订单号"
    if status == ChatStatus.FAILED and state.consecutive_tool_failures >= 2:
        return "业务工具连续失败，无法安全完成查询"
    return None


def _conversation_summary(history: list[dict[str, str]]) -> str:
    user_messages = [item["content"].strip() for item in history if item["role"] == "user"][-3:]
    compact = "；".join(message[:160] for message in user_messages if message)
    return f"近期客户诉求摘要：{compact or '未提供可摘要的客户消息'}"


def _deduplicate_sources(sources: list[Citation]) -> list[Citation]:
    unique: list[Citation] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        key = (source.document_id, source.paragraph_id)
        if key not in seen:
            unique.append(source)
            seen.add(key)
    return unique
