from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import (
    ChapterModel,
    DocumentChunkModel,
    DocumentModel,
    DocumentProfileModel,
    QuestionModel,
    QuestionSourceModel,
)
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


def test_import_material_creates_chapters_and_chunks(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "materials.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="测试课程"))
    material = tmp_path / "教材.md"
    material.write_text(
        "# 第一章 基础\n\n" + "基础内容。" * 100 + "\n\n# 第二章 应用\n应用内容。", encoding="utf-8"
    )

    service = DocumentService(engine)
    document = service.import_document(course.id, material)
    assert document.parse_status == "completed"
    assert document.chapter_count == 2
    assert document.chunk_count >= 2
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ChapterModel)) == 2
        assert session.scalar(select(func.count()).select_from(DocumentChunkModel)) >= 2

    with pytest.raises(ValueError, match="已经上传"):
        service.import_document(course.id, material)


def test_delete_material_cascades_parsed_content(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "delete.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="测试课程"))
    material = tmp_path / "教材.txt"
    material.write_text("第一章 内容\n正文", encoding="utf-8")
    service = DocumentService(engine)
    document = service.import_document(course.id, material)
    service.delete(document.id)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ChapterModel)) == 0


def test_parse_failure_is_persisted_for_audit(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "failed.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="测试课程"))
    material = tmp_path / "教材.exe"
    material.write_text("不是教材格式", encoding="utf-8")

    with pytest.raises(ValueError, match="不支持"):
        DocumentService(engine).import_document(course.id, material)

    with Session(engine) as session:
        document = session.scalar(select(DocumentModel))
        assert document is not None
        assert document.parse_status == "failed"
        assert "不支持" in document.parse_error


def test_scanned_pdf_is_marked_as_needing_ocr(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "ocr.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="测试课程"))
    material = tmp_path / "扫描教材.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    with material.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(ValueError, match="OCR"):
        DocumentService(engine).import_document(course.id, material)
    with Session(engine) as session:
        document = session.scalar(select(DocumentModel))
        assert document is not None
        assert document.parse_status == "failed"


def test_document_identity_missing_detection_and_safe_relink(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "relink.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="沪科版八年级数学"))
    source = tmp_path / "【沪科版】八年级下册(2025春版)数学电子课本.md"
    source.write_text("# 第19章 四边形\n\n四边形的内角和知识。", encoding="utf-8")
    service = DocumentService(engine)
    document = service.import_document(course.id, source)

    descriptor = service.describe(document.id, verify_hash=True)
    assert descriptor.identity.publisher == "沪科版"
    assert descriptor.identity.grade_level == "八年级"
    assert descriptor.identity.volume == "下册"
    assert descriptor.identity.edition == "2025春版"
    assert descriptor.health.ready_for_generation

    relocated = tmp_path / "new" / source.name
    relocated.parent.mkdir()
    source.rename(relocated)
    missing = service.inspect_document(document.id)
    assert missing.state == "missing"
    with pytest.raises(ValueError, match="重新定位"):
        service.assert_ready_for_generation(document.id)

    service.relink_document(document.id, relocated)
    assert service.inspect_document(document.id, verify_hash=True).state == "healthy"
    with Session(engine) as session:
        profile = session.scalar(select(DocumentProfileModel))
        assert profile is not None
        assert profile.file_state == "healthy"
        assert profile.volume == "下册"


def test_relink_rejects_different_file_and_replace_keeps_source_audit(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(tmp_path / "replace.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    old_file = tmp_path / "旧教材.md"
    old_file.write_text("# 19.1 多边形内角和\n\n旧版四边形教材依据。", encoding="utf-8")
    replacement = tmp_path / "新教材.md"
    replacement.write_text("# 19.2 平行四边形\n\n新版平行四边形教材依据。", encoding="utf-8")
    service = DocumentService(engine)
    document = service.import_document(course.id, old_file)
    old_chapter = service.list_chapters(document.id)[0]
    with Session(engine) as session, session.begin():
        old_chunk = session.scalar(
            select(DocumentChunkModel).where(
                DocumentChunkModel.chapter_id == old_chapter.id
            )
        )
        assert old_chunk is not None
        question = QuestionModel(
            course_id=course.id,
            question_type="填空题",
            stem="旧题",
            answer="答案",
            analysis="解析",
            difficulty=2,
            estimated_time_minutes=2,
            score=5,
        )
        session.add(question)
        session.flush()
        session.add(
            QuestionSourceModel(
                question_id=question.id,
                chunk_id=old_chunk.id,
                evidence="旧版四边形教材依据",
            )
        )
        old_chunk_id = old_chunk.id

    with pytest.raises(ValueError, match="替换并重新解析"):
        service.relink_document(document.id, replacement)
    service.replace_document(document.id, replacement)

    active = service.list_chapters(document.id)
    all_chapters = service.list_chapters(document.id, include_excluded=True)
    assert [chapter.title for chapter in active] == ["19.2 平行四边形"]
    assert any(chapter.id == old_chapter.id and chapter.is_excluded for chapter in all_chapters)
    with Session(engine) as session:
        source = session.scalar(select(QuestionSourceModel))
        assert source is not None and source.chunk_id == old_chunk_id
        assert session.get(DocumentChunkModel, old_chunk_id) is not None
    context = FtsRetriever(engine).scope_context(
        course.id, document_id=document.id, limit=10
    )
    assert context
    assert all(item.chapter_title == "19.2 平行四边形" for item in context)


def test_chapter_correction_updates_outline_and_exclusion(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "chapter-edit.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    material = tmp_path / "教材.md"
    material.write_text(
        "# 第19章 四边形\n总览。\n\n# 19.1 错误名称\n正文。",
        encoding="utf-8",
    )
    service = DocumentService(engine)
    document = service.import_document(course.id, material)
    chapters = service.list_chapters(document.id)
    target = chapters[-1]
    service.update_chapter(target.id, title="19.1 多边形内角和", page_start=3)
    assert service.list_chapters(document.id)[-1].title == "19.1 多边形内角和"
    assert service.list_chapters(document.id)[-1].page_start == 3

    service.set_chapter_excluded(target.id, True)
    assert target.id not in {chapter.id for chapter in service.list_chapters(document.id)}
    service.set_chapter_excluded(target.id, False)
    assert target.id in {chapter.id for chapter in service.list_chapters(document.id)}
