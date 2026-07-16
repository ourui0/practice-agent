from __future__ import annotations

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.knowledge_point_service import (
    KnowledgePointInput,
    KnowledgePointService,
)
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)


def test_extract_confirm_edit_and_delete_knowledge_points(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "knowledge.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    material = tmp_path / "教材.md"
    material.write_text("# 1.1 一次函数\n函数正文\n# 1.2 平行线\n几何正文", encoding="utf-8")
    DocumentService(engine).import_document(course.id, material)
    service = KnowledgePointService(engine)

    assert service.extract_candidates(course.id) == 2
    assert service.extract_candidates(course.id) == 0
    points = service.list(course.id)
    assert {point.name for point in points} == {"一次函数", "平行线"}
    assert all(point.status == "confirmed" for point in points)

    service.confirm(points[0].id)
    service.update(
        points[1].id,
        KnowledgePointInput(
            name="平行线的性质",
            importance=5,
            recommended_difficulty=4,
            recommended_question_types="选择题、证明题",
        ),
    )
    updated = service.list(course.id)
    assert all(point.status == "confirmed" for point in updated)
    assert any(point.name == "平行线的性质" and point.importance == 5 for point in updated)

    service.create_manual(course.id, KnowledgePointInput(name="补充知识点"))
    manual = next(point for point in service.list(course.id) if point.name == "补充知识点")
    assert manual.source == "manual"
    service.delete(manual.id)
    assert all(point.name != "补充知识点" for point in service.list(course.id))


def test_extract_skips_chapter_containers_and_confirms_valid_candidates(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "chapter_names.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    material = tmp_path / "教材.md"
    material.write_text(
        "# 第三章\n目录说明\n# 第14章 全等三角形\n章说明\n"
        "# 14.1 全等三角形\n具体知识内容\n# 14.2 三角形全等的判定\n具体知识内容",
        encoding="utf-8",
    )
    DocumentService(engine).import_document(course.id, material)
    service = KnowledgePointService(engine)

    assert service.extract_candidates(course.id) == 2
    points = service.list(course.id)
    assert {point.name for point in points} == {"全等三角形", "三角形全等的判定"}
    assert service.confirm_all_candidates(course.id) == 0
    assert all(point.status == "confirmed" for point in service.list(course.id))
