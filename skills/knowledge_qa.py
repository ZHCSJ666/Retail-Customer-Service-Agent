"""Grounded knowledge Skill that returns only retrievable merchant material."""

from __future__ import annotations

from app.schemas.api import ChatStatus, Citation, TraceEvent
from skills.base import SkillContext, SkillResult


class KnowledgeQASkill:
    skill_id = "knowledge_qa"

    def execute(self, context: SkillContext, *, order_id: str | None) -> SkillResult:
        del order_id  # Knowledge answers never use a user-supplied order ID.
        chunks = context.retriever.retrieve(merchant=context.merchant, question=context.message, limit=3)
        if not chunks:
            return SkillResult(
                answer="我无法在现有商家资料中核实这个问题，因此不作推测。你可以补充商品或政策关键词，或要求转人工。",
                status=ChatStatus.COMPLETED,
                state=context.state,
                trace=[
                    TraceEvent(
                        step=1,
                        action="local_retriever.search",
                        status="success",
                        summary="未召回可核实的知识片段。",
                    )
                ],
            )
        citations = [
            Citation(
                document_id=chunk.document_id,
                filename=chunk.filename,
                paragraph_id=chunk.paragraph_id,
                excerpt=chunk.content,
            )
            for chunk in chunks
        ]
        evidence = "\n".join(f"- 《{chunk.filename}》：{chunk.content}" for chunk in chunks)
        grounded_points = _grounded_points(context.message, [chunk.content for chunk in chunks])
        prefix = "\n".join(grounded_points) if grounded_points else "以下答复仅依据检索到的商家资料："
        return SkillResult(
            answer=f"{prefix}\n\n可核实的资料原文：\n{evidence}",
            status=ChatStatus.COMPLETED,
            state=context.state,
            sources=citations,
            trace=[
                TraceEvent(
                    step=1,
                    action="local_retriever.search",
                    status="success",
                    summary=f"召回 {len(chunks)} 个可引用知识片段。",
                )
            ],
        )


def _grounded_points(question: str, contents: list[str]) -> list[str]:
    """Produce only small conclusions whose supporting wording was retrieved."""

    joined = "\n".join(contents)
    points: list[str] = []
    if "防水" in question and "未标注防水或防尘等级" in joined:
        points.append("关于防水：商家资料未标注防水或防尘等级，无法确认具体防水能力。")
    if ("退" in question or "退款" in question) and "签收次日起 7 个自然日" in joined:
        points.append("关于退货窗口：资料写明，已签收且符合条件的商品可在签收次日起 7 个自然日内提交申请。")
    if points:
        points.append("以下为支撑上述结论的可核实资料原文：")
    return points
