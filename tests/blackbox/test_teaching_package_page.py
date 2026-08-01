from __future__ import annotations

from PySide6.QtWidgets import QApplication

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.knowledge_point_service import (
    KnowledgePointService,
)
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.retrieval import FtsRetriever
from edu_exam_agent.ui.pages.teaching_package_page import TeachingPackagePage


class _UnconfiguredProviders:
    def create_provider(self):
        raise ValueError("未配置")


def test_teaching_package_page_has_scoped_inputs_and_three_results(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    engine = create_database_engine(tmp_path / "teaching-page.db")
    initialize_database(engine)
    page = TeachingPackagePage(
        CourseService(engine),
        DocumentService(engine),
        KnowledgePointService(engine),
        _UnconfiguredProviders(),
        FtsRetriever(engine),
        engine,
    )
    page.resize(1100, 720)
    page.show()
    application.processEvents()

    assert page.tabs.count() == 3
    assert [page.tabs.tabText(index) for index in range(3)] == [
        "导学案",
        "教案",
        "教材依据",
    ]
    assert page.generate_button.text() == "生成导学案和教案"
    assert page.generate_button.isEnabled()
    assert not page.export_button.isEnabled()
    page.close()


def test_first_scoped_knowledge_point_is_ready_to_generate(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    engine = create_database_engine(tmp_path / "teaching-ready.db")
    initialize_database(engine)
    courses = CourseService(engine)
    course = courses.create(CourseInput(name="八年级数学"))
    material = tmp_path / "教材.md"
    material.write_text(
        "# 12.2 一次函数\n一次函数的一般形式是y=kx+b，其中k不等于0。",
        encoding="utf-8",
    )
    documents = DocumentService(engine)
    documents.import_document(course.id, material)
    points = KnowledgePointService(engine)
    points.extract_candidates(course.id)

    page = TeachingPackagePage(
        courses,
        documents,
        points,
        _UnconfiguredProviders(),
        FtsRetriever(engine),
        engine,
    )
    page.show()
    application.processEvents()

    assert page.course.currentData() == course.id
    assert page.document.currentData() is not None
    assert page._selected_chapter_ids()
    assert page._checked_point_ids()
    assert page.generate_button.isEnabled()
    page.close()
