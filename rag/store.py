"""SQLite FTS5-backed store for merchant knowledge and inspectable chunks."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: str
    filename: str
    paragraph_id: str
    content: str
    score: float


class SQLiteRagStore:
    """Keeps raw chunk provenance alongside an FTS5 index.

    Knowledge is stored and returned as data only. No content is evaluated as a
    prompt, SQL, code, or tool instruction.
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS rag_documents (
                        document_id TEXT PRIMARY KEY,
                        merchant_id TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        source_path TEXT NOT NULL,
                        imported_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS rag_chunks (
                        chunk_id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL,
                        merchant_id TEXT NOT NULL,
                        paragraph_id TEXT NOT NULL,
                        content TEXT NOT NULL,
                        FOREIGN KEY(document_id) REFERENCES rag_documents(document_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_rag_chunks_merchant ON rag_chunks(merchant_id);
                    CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
                        chunk_id UNINDEXED,
                        merchant_id UNINDEXED,
                        content
                    );
                    """
                )
        except sqlite3.OperationalError as exc:
            raise RuntimeError("SQLite FTS5 is required for the local knowledge index") from exc

    def replace_document(self, *, merchant_id: str, filename: str, source_path: str, content: str) -> int:
        document_id = _stable_id("doc", merchant_id, filename)
        chunks = _split_paragraphs(content)
        with self._connect() as connection:
            old_chunk_ids = connection.execute(
                "SELECT chunk_id FROM rag_chunks WHERE document_id = ?", (document_id,)
            ).fetchall()
            for row in old_chunk_ids:
                connection.execute("DELETE FROM rag_chunks_fts WHERE chunk_id = ?", (row["chunk_id"],))
            connection.execute("DELETE FROM rag_chunks WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM rag_documents WHERE document_id = ?", (document_id,))
            connection.execute(
                """
                INSERT INTO rag_documents(document_id, merchant_id, filename, source_path, imported_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (document_id, merchant_id, filename, source_path, _utc_now()),
            )
            for index, chunk in enumerate(chunks, start=1):
                paragraph_id = f"p-{index:03d}"
                chunk_id = _stable_id("chunk", document_id, paragraph_id)
                connection.execute(
                    """
                    INSERT INTO rag_chunks(chunk_id, document_id, merchant_id, paragraph_id, content)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (chunk_id, document_id, merchant_id, paragraph_id, chunk),
                )
                connection.execute(
                    "INSERT INTO rag_chunks_fts(chunk_id, merchant_id, content) VALUES (?, ?, ?)",
                    (chunk_id, merchant_id, chunk),
                )
        return len(chunks)

    def search(self, *, merchant_id: str, query: str, limit: int = 3) -> list[RetrievedChunk]:
        """Search with FTS5 first, then a Chinese-friendly lexical fallback."""

        if not query.strip():
            return []
        fts_scores = self._fts_scores(merchant_id, query)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.chunk_id, c.document_id, d.filename, c.paragraph_id, c.content
                FROM rag_chunks AS c
                JOIN rag_documents AS d ON d.document_id = c.document_id
                WHERE c.merchant_id = ?
                """,
                (merchant_id,),
            ).fetchall()

        hits: list[RetrievedChunk] = []
        for row in rows:
            lexical_score = _lexical_score(query, row["content"])
            fts_score = fts_scores.get(row["chunk_id"], 0.0)
            score = lexical_score + fts_score
            if score <= 0:
                continue
            hits.append(
                RetrievedChunk(
                    document_id=row["document_id"],
                    filename=row["filename"],
                    paragraph_id=row["paragraph_id"],
                    content=row["content"],
                    score=score,
                )
            )
        ordered = sorted(hits, key=lambda item: (-item.score, item.filename, item.paragraph_id))
        # Diverse document sources are more useful for compound retail questions
        # than three adjacent paragraphs from one policy document.
        selected: list[RetrievedChunk] = []
        seen_documents: set[str] = set()
        for hit in ordered:
            if hit.document_id not in seen_documents:
                selected.append(hit)
                seen_documents.add(hit.document_id)
                if len(selected) == limit:
                    return selected
        for hit in ordered:
            if hit not in selected:
                selected.append(hit)
                if len(selected) == limit:
                    break
        return selected

    def document_count(self, merchant_id: str) -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM rag_documents WHERE merchant_id = ?", (merchant_id,)
                ).fetchone()[0]
            )

    def _fts_scores(self, merchant_id: str, query: str) -> dict[str, float]:
        terms = _fts_terms(query)
        if not terms:
            return {}
        expression = " OR ".join(f'"{term}"' for term in terms)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT chunk_id, bm25(rag_chunks_fts) AS rank
                    FROM rag_chunks_fts
                    WHERE rag_chunks_fts MATCH ? AND merchant_id = ?
                    LIMIT 20
                    """,
                    (expression, merchant_id),
                ).fetchall()
        except sqlite3.OperationalError:
            # Lexical fallback remains safe if an FTS query token is unsupported.
            return {}
        # bm25 is lower-is-better, while the fallback scorer is higher-is-better.
        return {row["chunk_id"]: max(0.1, 10.0 - float(row["rank"])) for row in rows}


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _split_paragraphs(content: str, max_chars: int = 700) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    chunks: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            chunks.append(paragraph)
            continue
        for start in range(0, len(paragraph), max_chars):
            chunks.append(paragraph[start : start + max_chars])
    return chunks or ["（空文档）"]


def _fts_terms(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", query)
    return list(dict.fromkeys(terms))[:8]


def _lexical_score(query: str, content: str) -> float:
    stop_characters = set("这那我你他她它的是了在和与吗呢请帮一下个买了能否如果明天为什么")
    chinese_chars = {char for char in query if "\u4e00" <= char <= "\u9fff" and char not in stop_characters}
    score = sum(min(content.count(char), 2) for char in chinese_chars)
    for token in re.findall(r"[A-Za-z0-9_-]{2,}", query.lower()):
        if token in content.lower():
            score += 4
    return float(score)
