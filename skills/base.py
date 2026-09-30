"""Common Skill execution contracts and global tool-step budget."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agent.contracts import ConversationState
from app.core.config import LoadedMerchant
from app.schemas.api import ChatError, ChatStatus, Citation, HandoffInfo, TraceEvent
from rag.retrieve import LocalRetriever
from tools.protocols import MerchantToolSet


class ToolStepBudget:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.used = 0

    def claim(self) -> bool:
        if self.used >= self.maximum:
            return False
        self.used += 1
        return True


@dataclass(frozen=True)
class SkillContext:
    merchant: LoadedMerchant
    session_id: str
    customer_id: str
    tools: MerchantToolSet
    state: ConversationState
    tool_budget: ToolStepBudget
    retriever: LocalRetriever
    message: str
    conversation_summary: str
    handoff_reason: str | None = None


@dataclass
class SkillResult:
    answer: str
    status: ChatStatus
    state: ConversationState
    trace: list[TraceEvent] = field(default_factory=list)
    sources: list[Citation] = field(default_factory=list)
    handoff: HandoffInfo | None = None
    error: ChatError | None = None


class Skill(Protocol):
    skill_id: str

    def execute(self, context: SkillContext, *, order_id: str | None) -> SkillResult: ...
