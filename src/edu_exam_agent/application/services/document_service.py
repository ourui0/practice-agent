"""Transactional material import and persistence workflow."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from edu_exam_agent.application.services.document_processing import (
    create_chunks,
    recognize_chapters,
    recognize_table_of_contents,
)
from edu_exam_agent.infrastructure.database.models import (
    ChapterModel,
    DocumentChunkModel,
    DocumentModel,
    DocumentProfileModel,
)
from edu_exam_agent.infrastructure.parsers import ParsedDocument, ParserRegistry
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


@dataclass(frozen=True, slots=True)
class ChapterOutlineSection:
    title: str
    chapter_id: int


@dataclass(frozen=True, slots=True)
class ChapterOutlineItem:
    title: str
    chapter_ids: tuple[int, ...]
    sections: tuple[ChapterOutlineSection, ...]


@dataclass(frozen=True, slots=True)
class DocumentIdentity:
    publisher: str = ""
    grade_level: str = ""
    volume: str = ""
    edition: str = ""

    @property
    def display_name(self) -> str:
        parts = tuple(
            value
            for value in (self.publisher, self.grade_level, self.volume, self.edition)
            if value
        )
        return " · ".join(parts) if parts else "未识别版本信息"


@dataclass(frozen=True, slots=True)
class DocumentHealth:
    state: str
    message: str
    ready_for_generation: bool


@dataclass(frozen=True, slots=True)
class DocumentDescriptor:
    document: DocumentModel
    identity: DocumentIdentity
    health: DocumentHealth


class DocumentService:
    def __init__(self, engine: Engine, max_file_size: int = 200 * 1024 * 1024) -> None:
        self._engine = engine
        self._max_file_size = max_file_size
        self._parsers = ParserRegistry()
        self._outline_cache: dict[int, tuple[ChapterOutlineItem, ...]] = {}

    def list(self, course_id: int) -> list[DocumentModel]:
        with Session(self._engine) as session:
            return list(
                session.scalars(select(DocumentModel).where(DocumentModel.course_id == course_id))
            )

    def list_descriptors(self, course_id: int) -> list[DocumentDescriptor]:
        return [self.describe(document.id) for document in self.list(course_id)]

    def list_chapters(
        self, document_id: int, *, include_excluded: bool = False
    ) -> list[ChapterModel]:
        with Session(self._engine) as session:
            statement = (
                select(ChapterModel)
                .where(ChapterModel.document_id == document_id)
                .order_by(ChapterModel.position)
            )
            if not include_excluded:
                statement = statement.where(ChapterModel.is_excluded.is_(False))
            return list(session.scalars(statement))

    def chapter_outline(self, document_id: int) -> tuple[ChapterOutlineItem, ...]:
        cached = self._outline_cache.get(document_id)
        if cached is not None:
            return cached
        chapters = [
            chapter
            for chapter in self.list_chapters(document_id)
            if not chapter.is_excluded
        ]
        major_rows: dict[str, ChapterModel] = {}
        section_rows: dict[str, list[ChapterModel]] = {}
        for chapter in chapters:
            major = re.match(r"^第\s*(\d+)\s*章", chapter.title)
            section = re.match(r"^(\d+)\.(\d+)\s+", chapter.title)
            if major:
                major_rows[major.group(1)] = chapter
            elif section:
                section_rows.setdefault(section.group(1), []).append(chapter)

        toc = []
        with Session(self._engine) as session:
            document = session.get(DocumentModel, document_id)
            source_path = Path(document.original_path) if document is not None else None
        if source_path is not None and source_path.is_file():
            try:
                toc = recognize_table_of_contents(self._parsers.parse(source_path))
            except Exception:
                toc = []

        toc_by_number = {item.number: item for item in toc}
        numbers = list(toc_by_number)
        for number in (*major_rows, *section_rows):
            if number not in numbers:
                numbers.append(number)

        outline: list[ChapterOutlineItem] = []
        for number in numbers:
            rows = sorted(section_rows.get(number, []), key=lambda row: row.position)
            major_row = major_rows.get(number)
            toc_item = toc_by_number.get(number)
            title = (
                toc_item.title
                if toc_item is not None
                else major_row.title if major_row is not None else f"第{number}章"
            )
            sections: list[ChapterOutlineSection] = []
            for index, row in enumerate(rows):
                section_title = row.title
                if toc_item is not None and index < len(toc_item.sections):
                    section_title = f"{number}.{index + 1} {toc_item.sections[index]}"
                sections.append(ChapterOutlineSection(section_title, row.id))
            ids = tuple(
                [major_row.id] if major_row is not None else []
            ) + tuple(section.chapter_id for section in sections)
            if ids:
                outline.append(ChapterOutlineItem(title, ids, tuple(sections)))

        if not outline:
            outline = [
                ChapterOutlineItem(chapter.title, (chapter.id,), ()) for chapter in chapters
            ]
        result = tuple(outline)
        self._outline_cache[document_id] = result
        return result

    def describe(self, document_id: int, *, verify_hash: bool = False) -> DocumentDescriptor:
        with Session(self._engine) as session:
            document = session.get(DocumentModel, document_id)
            if document is None:
                raise ValueError("教材记录不存在")
            session.expunge(document)
        identity = self.detect_identity(document.filename)
        health = self.inspect_document(document_id, verify_hash=verify_hash)
        return DocumentDescriptor(document, identity, health)

    def inspect_document(
        self, document_id: int, *, verify_hash: bool = False
    ) -> DocumentHealth:
        with Session(self._engine) as session, session.begin():
            document = session.get(DocumentModel, document_id)
            if document is None:
                raise ValueError("教材记录不存在")
            identity = self.detect_identity(document.filename)
            path = Path(document.original_path)
            active_chapters = list(
                session.scalars(
                    select(ChapterModel.id).where(
                        ChapterModel.document_id == document_id,
                        ChapterModel.is_excluded.is_(False),
                    )
                )
            )
            if not path.is_file():
                health = DocumentHealth(
                    "missing",
                    "原文件已移动或删除，请重新定位教材文件。",
                    False,
                )
            elif document.parse_status != "completed":
                health = DocumentHealth(
                    "parse_failed",
                    document.parse_error or "教材尚未成功解析，请重新解析。",
                    False,
                )
            elif not active_chapters or document.chunk_count < 1:
                health = DocumentHealth(
                    "incomplete",
                    "教材没有可用章节或文本块，请重新解析并检查目录。",
                    False,
                )
            elif path.stat().st_size != document.file_size:
                health = DocumentHealth(
                    "changed",
                    "原文件内容可能已发生变化，请选择替换并重新解析。",
                    False,
                )
            elif verify_hash and self._file_hash(path) != document.file_hash:
                health = DocumentHealth(
                    "changed",
                    "原文件校验值已变化，请选择替换并重新解析。",
                    False,
                )
            else:
                health = DocumentHealth("healthy", "文件与解析索引均可用。", True)
            self._upsert_profile(session, document, identity, health)
            return health

    def assert_ready_for_generation(self, document_id: int) -> None:
        health = self.inspect_document(document_id)
        if not health.ready_for_generation:
            raise ValueError(f"教材当前不可用于生成：{health.message}")

    def relink_document(self, document_id: int, path: Path) -> DocumentModel:
        """Point a missing record to the same file at a new location."""
        self._validate_source_file(path)
        digest = self._file_hash(path)
        with Session(self._engine) as session, session.begin():
            document = session.get(DocumentModel, document_id)
            if document is None:
                raise ValueError("教材记录不存在")
            if digest != document.file_hash:
                raise ValueError("所选文件与原教材内容不同，请使用“替换并重新解析”。")
            document.original_path = str(path)
            document.filename = path.name
            document.file_type = path.suffix.lower()
            document.file_size = path.stat().st_size
            identity = self.detect_identity(path.name)
            health = DocumentHealth("healthy", "已重新定位，文件与原教材一致。", True)
            self._upsert_profile(session, document, identity, health)
            session.flush()
            session.refresh(document)
            session.expunge(document)
            relocated = document
        self._outline_cache.pop(document_id, None)
        return relocated

    def reparse_document(self, document_id: int) -> DocumentModel:
        with Session(self._engine) as session:
            document = session.get(DocumentModel, document_id)
            if document is None:
                raise ValueError("教材记录不存在")
            path = Path(document.original_path)
        return self._replace_parsed_content(document_id, path, allow_different_file=False)

    def replace_document(self, document_id: int, path: Path) -> DocumentModel:
        return self._replace_parsed_content(document_id, path, allow_different_file=True)

    def update_chapter(
        self,
        chapter_id: int,
        *,
        title: str,
        page_start: int,
    ) -> ChapterModel:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("章节名称不能为空")
        if page_start < 1:
            raise ValueError("起始页必须大于0")
        with Session(self._engine) as session, session.begin():
            chapter = session.get(ChapterModel, chapter_id)
            if chapter is None:
                raise ValueError("章节不存在")
            chapter.title = clean_title
            chapter.page_start = page_start
            document_id = chapter.document_id
            document = session.get(DocumentModel, document_id)
            course_id = document.course_id if document is not None else None
            session.flush()
            session.refresh(chapter)
            session.expunge(chapter)
            updated = chapter
        self._outline_cache.pop(document_id, None)
        if course_id is not None:
            FtsRetriever(self._engine).rebuild(course_id)
        return updated

    def set_chapter_excluded(self, chapter_id: int, excluded: bool) -> None:
        with Session(self._engine) as session, session.begin():
            chapter = session.get(ChapterModel, chapter_id)
            if chapter is None:
                raise ValueError("章节不存在")
            if excluded:
                remaining = session.scalar(
                    select(ChapterModel.id).where(
                        ChapterModel.document_id == chapter.document_id,
                        ChapterModel.id != chapter.id,
                        ChapterModel.is_excluded.is_(False),
                    ).limit(1)
                )
                if remaining is None:
                    raise ValueError("教材至少需要保留一个可用章节")
            chapter.is_excluded = excluded
            document_id = chapter.document_id
            document = session.get(DocumentModel, document_id)
            course_id = document.course_id if document is not None else None
            active_count = len(
                list(
                    session.scalars(
                        select(ChapterModel.id).where(
                            ChapterModel.document_id == document_id,
                            ChapterModel.is_excluded.is_(False),
                        )
                    )
                )
            )
            if document is not None:
                document.chapter_count = active_count
                document.chunk_count = int(
                    session.scalar(
                        select(func.count(DocumentChunkModel.id))
                        .join(
                            ChapterModel,
                            ChapterModel.id == DocumentChunkModel.chapter_id,
                        )
                        .where(
                            DocumentChunkModel.document_id == document_id,
                            ChapterModel.is_excluded.is_(False),
                        )
                    )
                    or 0
                )
        self._outline_cache.pop(document_id, None)
        if course_id is not None:
            FtsRetriever(self._engine).rebuild(course_id)

    @staticmethod
    def detect_identity(filename: str) -> DocumentIdentity:
        name = Path(filename).stem
        publisher_match = re.search(r"【([^】]+)】", name)
        grade_match = re.search(r"([一二三四五六七八九1-9])年级", name)
        volume_match = re.search(r"(上册|下册)", name)
        edition_match = re.search(r"(\d{4}(?:春|秋)?版)", name)
        return DocumentIdentity(
            publisher=publisher_match.group(1) if publisher_match else "",
            grade_level=f"{grade_match.group(1)}年级" if grade_match else "",
            volume=volume_match.group(1) if volume_match else "",
            edition=edition_match.group(1) if edition_match else "",
        )

    def import_document(self, course_id: int, path: Path) -> DocumentModel:
        self._validate_source_file(path, validate_format=False)
        size = path.stat().st_size
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
            session.flush()
            self._upsert_profile(
                session,
                document,
                self.detect_identity(path.name),
                DocumentHealth("pending", "等待解析。", False),
            )
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
                    self._upsert_profile(
                        session,
                        failed,
                        self.detect_identity(failed.filename),
                        DocumentHealth("parse_failed", failed.parse_error, False),
                    )
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
            self._upsert_profile(
                session,
                document,
                self.detect_identity(document.filename),
                DocumentHealth("healthy", "文件与解析索引均可用。", True),
            )
            session.flush()
            session.refresh(document)
            session.expunge(document)
            imported = document
        FtsRetriever(self._engine).rebuild(course_id)
        self._outline_cache.pop(document_id, None)
        return imported

    def _replace_parsed_content(
        self, document_id: int, path: Path, *, allow_different_file: bool
    ) -> DocumentModel:
        self._validate_source_file(path)
        digest = self._file_hash(path)
        with Session(self._engine) as session:
            document = session.get(DocumentModel, document_id)
            if document is None:
                raise ValueError("教材记录不存在")
            course_id = document.course_id
            old_digest = document.file_hash
            previous_status = document.parse_status
            duplicate = session.scalar(
                select(DocumentModel.id).where(
                    DocumentModel.course_id == course_id,
                    DocumentModel.file_hash == digest,
                    DocumentModel.id != document_id,
                )
            )
        if duplicate is not None:
            raise ValueError("同一课程中已经存在这份教材")
        if not allow_different_file and digest != old_digest:
            raise ValueError("原文件内容已经变化，请使用“替换并重新解析”。")

        try:
            parsed = self._parsers.parse(path)
            if path.suffix.lower() == ".pdf":
                self._validate_extraction(parsed)
            chapters = recognize_chapters(parsed)
            if not chapters:
                raise ValueError("没有识别到可用章节")
        except Exception as exc:
            with Session(self._engine) as session, session.begin():
                document = session.get(DocumentModel, document_id)
                if document is not None:
                    if previous_status != "completed":
                        document.parse_status = "failed"
                    document.parse_error = str(exc)[:2000]
                    self._upsert_profile(
                        session,
                        document,
                        self.detect_identity(path.name),
                        DocumentHealth("parse_failed", document.parse_error, False),
                    )
            raise

        with Session(self._engine) as session, session.begin():
            document = session.get(DocumentModel, document_id)
            if document is None:
                raise ValueError("教材记录不存在")
            for old_chapter in session.scalars(
                select(ChapterModel).where(
                    ChapterModel.document_id == document_id,
                    ChapterModel.is_excluded.is_(False),
                )
            ):
                old_chapter.is_excluded = True

            chunk_count = 0
            start_position = (
                session.scalar(
                    select(ChapterModel.position)
                    .where(ChapterModel.document_id == document_id)
                    .order_by(ChapterModel.position.desc())
                    .limit(1)
                )
                or 0
            )
            for offset, chapter in enumerate(chapters, 1):
                chapter_row = ChapterModel(
                    document_id=document.id,
                    title=chapter.title,
                    position=start_position + offset,
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
                            course_id=document.course_id,
                            page_start=chunk.page_start,
                            page_end=chunk.page_end,
                            content=chunk.content,
                            character_count=chunk.character_count,
                        )
                    )
                    chunk_count += 1
            document.filename = path.name
            document.original_path = str(path)
            document.file_type = path.suffix.lower()
            document.file_size = path.stat().st_size
            document.file_hash = digest
            document.parse_status = "completed"
            document.parse_error = ""
            document.page_count = len(parsed.pages)
            document.chapter_count = len(chapters)
            document.chunk_count = chunk_count
            self._upsert_profile(
                session,
                document,
                self.detect_identity(path.name),
                DocumentHealth("healthy", "已完成解析，旧解析快照已保留。", True),
            )
            session.flush()
            session.refresh(document)
            session.expunge(document)
            replaced = document
        FtsRetriever(self._engine).rebuild(course_id)
        self._outline_cache.pop(document_id, None)
        return replaced

    def _validate_source_file(self, path: Path, *, validate_format: bool = True) -> None:
        if not path.is_file():
            raise ValueError("教材文件不存在")
        if validate_format and path.suffix.lower() not in {
            ".pdf",
            ".docx",
            ".txt",
            ".md",
            ".markdown",
        }:
            raise ValueError("不支持的教材格式")
        if path.stat().st_size > self._max_file_size:
            raise ValueError("教材文件超过大小限制")

    @staticmethod
    def _upsert_profile(
        session: Session,
        document: DocumentModel,
        identity: DocumentIdentity,
        health: DocumentHealth,
    ) -> None:
        profile = session.scalar(
            select(DocumentProfileModel).where(
                DocumentProfileModel.document_id == document.id
            )
        )
        values = {
            "publisher": identity.publisher,
            "grade_level": identity.grade_level,
            "volume": identity.volume,
            "edition": identity.edition,
            "file_state": health.state,
            "validation_message": health.message,
            "last_checked_at": datetime.now(),
        }
        if profile is None:
            session.add(DocumentProfileModel(document_id=document.id, **values))
        else:
            for name, value in values.items():
                setattr(profile, name, value)

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
                self._outline_cache.pop(document_id, None)
                FtsRetriever(self._engine).rebuild(course_id)
