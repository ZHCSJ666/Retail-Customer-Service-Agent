"""Controlled ingestion of configured Markdown/TXT merchant knowledge."""

from __future__ import annotations

from app.core.config import LoadedMerchant
from rag.store import SQLiteRagStore


def ingest_merchant_knowledge(merchant: LoadedMerchant, store: SQLiteRagStore) -> dict[str, int]:
    files = sorted(merchant.knowledge_dir.glob("*.md")) + sorted(merchant.knowledge_dir.glob("*.txt"))
    if not files:
        raise RuntimeError(f"No Markdown/TXT knowledge files in {merchant.knowledge_dir}")
    chunks = 0
    for path in files:
        chunks += store.replace_document(
            merchant_id=merchant.config.merchant_id,
            filename=path.name,
            source_path=str(path.relative_to(merchant.resolve_project_path("."))),
            content=path.read_text(encoding="utf-8"),
        )
    return {"documents": len(files), "chunks": chunks}

