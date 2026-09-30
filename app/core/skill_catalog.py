"""Declarative core Skill metadata.

The executable implementations arrive in later phases. Exposing their declared
contracts now lets the API distinguish configured capability from enabled runtime
execution rather than pretending a stub is an agent.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    description: str
    input_schema: str
    output_schema: str
    tool_dependencies: tuple[str, ...]
    implementation_status: str = "planned"


CORE_SKILLS: tuple[SkillDefinition, ...] = (
    SkillDefinition(
        skill_id="knowledge_qa",
        description="检索商家知识库，并输出可追溯的回答材料与引用。",
        input_schema="KnowledgeQuestionInput",
        output_schema="KnowledgeAnswer",
        tool_dependencies=("retriever",),
    ),
    SkillDefinition(
        skill_id="order_lookup",
        description="按当前会话客户校验归属后查询订单和物流。",
        input_schema="OrderLookupInput",
        output_schema="OrderLookupResult",
        tool_dependencies=("order", "shipping"),
    ),
    SkillDefinition(
        skill_id="refund_eligibility",
        description="依据订单数据与商家确定性规则判断申请资格。",
        input_schema="RefundEligibilityInput",
        output_schema="RefundEligibilityResult",
        tool_dependencies=("order", "refund_rules"),
    ),
    SkillDefinition(
        skill_id="human_handoff",
        description="创建包含摘要和升级原因的模拟人工工单。",
        input_schema="HumanHandoffInput",
        output_schema="HandoffTicket",
        tool_dependencies=("handoff",),
    ),
)


def configured_skills(enabled_ids: list[str], active_ids: set[str] | None = None) -> list[dict[str, object]]:
    enabled = set(enabled_ids)
    active = active_ids or set()
    return [
        {
            "skill_id": skill.skill_id,
            "description": skill.description,
            "input_schema": skill.input_schema,
            "output_schema": skill.output_schema,
            "tool_dependencies": list(skill.tool_dependencies),
            "enabled_in_merchant_config": skill.skill_id in enabled,
            "implementation_status": "active" if skill.skill_id in active else skill.implementation_status,
        }
        for skill in CORE_SKILLS
    ]
