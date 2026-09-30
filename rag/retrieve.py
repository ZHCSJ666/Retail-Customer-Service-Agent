"""Retriever interface over the local SQLite knowledge store."""

from __future__ import annotations

from app.core.config import LoadedMerchant
from rag.store import RetrievedChunk, SQLiteRagStore


class LocalRetriever:
    def __init__(self, store: SQLiteRagStore) -> None:
        self.store = store

    def retrieve(self, *, merchant: LoadedMerchant, question: str, limit: int = 3) -> list[RetrievedChunk]:
        return self.store.search(merchant_id=merchant.config.merchant_id, query=question, limit=limit)

