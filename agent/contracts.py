"""Validated contracts between model adapter, router and Skills."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentName(str, Enum):
    ORDER_LOOKUP = "order_lookup"
    KNOWLEDGE_QA = "knowledge_qa"
    REFUND_ELIGIBILITY = "refund_eligibility"
    HUMAN_HANDOFF = "human_handoff"
    UNKNOWN = "unknown"


class ExtractedIntent(AgentModel):
    intent: IntentName
    order_id: str | None = Field(
        default=None, min_length=3, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
    )
    rationale: str = Field(min_length=1, max_length=200)


class IntentExtraction(AgentModel):
    intents: list[ExtractedIntent] = Field(min_length=1, max_length=4)


class ConversationState(AgentModel):
    """Only short-lived routing state; business truth always comes from tools."""

    awaiting_order_id: bool = False
    pending_order_skill: IntentName | None = None
    order_lookup_prompt_count: int = Field(default=0, ge=0, le=3)
    consecutive_tool_failures: int = Field(default=0, ge=0, le=10)
