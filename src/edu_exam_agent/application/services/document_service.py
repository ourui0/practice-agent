"""Transactional material import and persistence workflow."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from edu_exam_agent.application.services.document_processing import (
    create_chunks,
    recognize_chapters,
)
from edu_exam_agent.infrastructure.database.models import (
    ChapterModel,
    DocumentChunkModel,
    DocumentModel,
)
from edu_exam_agent.infrastructure.parsers import ParsedDocument, ParserRegistry
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


class DocumentService:
    def __init__(self, engine: Engine, max_file_size: int = 100 * 1024 * 1024) -> None:
        self._engine = engine
        self._max_file_size = max_file_size
        self._parsers = ParserRegistry()

    def list(self, course_id: int) -> list[DocumentModel]:
        with Session(self._engine) as session:
            return list(
                session.scalars(select(DocumentModel).where(DocumentModel.course_id == course_id))
            )

    def list_chapters(self, document_id: int) -> list[ChapterModel]:
        with Session(self._engine) as session:
            statement = (
                select(ChapterModel)
                .where(ChapterModel.document_id == document_id)
                .order_by(ChapterModel.position)
            )
            return list(session.scalars(statement))

    def import_document(self, course_id: int, path: Path) -> DocumentModel:
        if not path.is_file():
            raise ValueError("教材文件不存在")
        size = path.stat().st_size
        if size > self._max_file_size:
            raise ValueError("教材文件超过大小限制")
        digest = self._file_hash(path)
        with Session(self._engine) as session:
            duplicate = session.scalar(
                select(DocumentModel).where(
                    DocumentModel.course_id == course_id, DocumentModel.file_hash == digest
                )
            )
            if duplicate:
                raise ValueError("该课程已经上传过相同教材")
            document = DocumentModel(
                course_id=course_id,
                filename=path.name,
                original_path=str(path),
                file_type=path.suffix.lower(),
                file_size=size,
                file_hash=digest,
                parse_status="pending",
            )
            session.add(document)
            session.commit()
            session.refresh(document)
            document_id = document.id

        try:
            parsed = self._parsers.parse(path)
            if path.suffix.lower() == ".pdf":
                self._validate_extraction(parsed)
            chapters = recognize_chapters(parsed)
        except Exception as exc:
            with Session(self._engine) as session:
                failed = session.get(DocumentModel, document_id)
                if failed is not None:
                    failed.parse_status = "failed"
                    failed.parse_error = str(exc)[:2000]
                    session.commit()
            raise

        with Session(self._engine) as session, session.begin():
            document = session.get(DocumentModel, document_id)
            if document is None:
                raise ValueError("教材记录不存在")
            document.parse_status = "completed"
            document.page_count = len(parsed.pages)
            document.chapter_count = len(chapters)
            chunk_count = 0
            for position, chapter in enumerate(chapters, 1):
                chapter_row = ChapterModel(
                    document_id=document.id,
                    title=chapter.title,
                    position=position,
                    page_start=chapter.page_start,
                    content=chapter.content,
                )
                session.add(chapter_row)
                session.flush()
                for chunk in create_chunks([chapter]):
                    session.add(
                        DocumentChunkModel(
                            document_id=document.id,
                            chapter_id=chapter_row.id,
                            course_id=course_id,
                            page_start=chunk.page_start,
                            page_end=chunk.page_end,
                            content=chunk.content,
                            character_count=chunk.character_count,
                        )
                    )
                    chunk_count += 1
            document.chunk_count = chunk_count
            session.flush()
            session.refresh(document)
            session.expunge(document)
            imported = document
        FtsRetriever(self._engine).rebuild(course_id)
        return imported

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _validate_extraction(parsed: ParsedDocument) -> None:
        if not parsed.pages:
            raise ValueError("教材没有可读取的页面")
        nonempty = sum(bool(page.text.strip()) for page in parsed.pages)
        characters = sum(len(page.text.strip()) for page in parsed.pages)
        if nonempty / len(parsed.pages) < 0.2 or characters < 500:
            raise ValueError("PDF有效文本过少，可能是扫描版，需要启用OCR后重新解析")
        if parsed.page_errors / len(parsed.pages) > 0.2:
            raise ValueError("PDF损坏页面过多，无法可靠解析")

    def delete(self, document_id: int) -> None:
        with Session(self._engine) as session:
            document = session.get(DocumentModel, document_id)
            if document:
                course_id = document.course_id
                session.delete(document)
                session.commit()
                FtsRetriever(self._engine).rebuild(course_id)
