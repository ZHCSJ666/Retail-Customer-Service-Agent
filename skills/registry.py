"""Skill registry: only registered Skills are executable by the orchestrator."""

from __future__ import annotations

from skills.base import Skill
from skills.human_handoff import HumanHandoffSkill
from skills.knowledge_qa import KnowledgeQASkill
from skills.order_lookup import OrderLookupSkill
from skills.refund_eligibility import RefundEligibilitySkill


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if skill.skill_id in self._skills:
            raise RuntimeError(f"Duplicate Skill registration: {skill.skill_id}")
        self._skills[skill.skill_id] = skill

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def active_ids(self) -> set[str]:
        return set(self._skills)


def build_core_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(OrderLookupSkill())
    registry.register(KnowledgeQASkill())
    registry.register(RefundEligibilitySkill())
    registry.register(HumanHandoffSkill())
    return registry
