"""SQLite FTS5 retrieval constrained by teaching scope."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from edu_exam_agent.infrastructure.database.models import (
    ChapterModel,
    DocumentChunkModel,
    DocumentModel,
)


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk_id: int
    document_id: int
    chapter_id: int
    document_name: str
    chapter_title: str
    page_start: int
    page_end: int
    excerpt: str
    rank: float


class FtsRetriever:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def search(
        self,
        query: str,
        course_id: int,
        document_id: int | None = None,
        chapter_ids: list[int] | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        if len(query.strip()) < 2:
            raise ValueError("检索词至少需要两个字符")
        filters = ["f.course_id = :course_id"]
        parameters: dict[str, object] = {
            "query": query.strip(),
            "course_id": course_id,
            "limit": min(max(limit, 1), 100),
        }
        if document_id is not None:
            filters.append("f.document_id = :document_id")
            parameters["document_id"] = document_id
        if chapter_ids:
            names = []
            for index, chapter_id in enumerate(chapter_ids):
                name = f"chapter_{index}"
                names.append(f":{name}")
                parameters[name] = chapter_id
            filters.append(f"f.chapter_id IN ({','.join(names)})")
        statement = text(
            f"""SELECT c.id, c.document_id, c.chapter_id, d.filename, h.title,
            c.page_start, c.page_end,
            snippet(document_chunks_fts, 4, '[', ']', '…', 24),
            bm25(document_chunks_fts)
            FROM document_chunks_fts f
            JOIN document_chunks c ON c.id = CAST(f.chunk_id AS INTEGER)
            JOIN documents d ON d.id = c.document_id
            JOIN chapters h ON h.id = c.chapter_id
            WHERE document_chunks_fts MATCH :query AND {" AND ".join(filters)}
            ORDER BY bm25(document_chunks_fts) LIMIT :limit"""
        )
        with self._engine.connect() as connection:
            return [SearchResult(*row) for row in connection.execute(statement, parameters)]

    def rebuild(self, course_id: int | None = None) -> int:
        where = "WHERE course_id = :course_id" if course_id is not None else ""
        parameters = {"course_id": course_id} if course_id is not None else {}
        with self._engine.begin() as connection:
            if course_id is None:
                connection.execute(text("DELETE FROM document_chunks_fts"))
            else:
                connection.execute(
                    text("DELETE FROM document_chunks_fts WHERE course_id = :course_id"),
                    parameters,
                )
            result = connection.execute(
                text(
                    f"""INSERT INTO document_chunks_fts(
                    chunk_id, course_id, document_id, chapter_id, content)
                    SELECT id, course_id, document_id, chapter_id, content
                    FROM document_chunks {where}"""
                ),
                parameters,
            )
            return result.rowcount

    def scope_context(
        self,
        course_id: int,
        document_id: int | None = None,
        chapter_ids: list[int] | None = None,
        limit: int = 5,
    ) -> list[SearchResult]:
        """Return deterministic textbook chunks when a scoped FTS phrase has no match."""
        statement = (
            select(
                DocumentChunkModel.id,
                DocumentChunkModel.document_id,
                DocumentChunkModel.chapter_id,
                DocumentModel.filename,
                ChapterModel.title,
                DocumentChunkModel.page_start,
                DocumentChunkModel.page_end,
                DocumentChunkModel.content,
            )
            .join(DocumentModel, DocumentModel.id == DocumentChunkModel.document_id)
            .join(ChapterModel, ChapterModel.id == DocumentChunkModel.chapter_id)
            .where(DocumentChunkModel.course_id == course_id)
            .order_by(DocumentChunkModel.page_start, DocumentChunkModel.id)
            .limit(min(max(limit, 1), 20))
        )
        if document_id is not None:
            statement = statement.where(DocumentChunkModel.document_id == document_id)
        if chapter_ids:
            statement = statement.where(DocumentChunkModel.chapter_id.in_(chapter_ids))
        with Session(self._engine) as session:
            return [
                SearchResult(*row[:7], row[7][:600], 0.0)
                for row in session.execute(statement)
            ]
