from __future__ import annotations

from PySide6.QtWidgets import QApplication
from sqlalchemy.orm import Session

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import QuestionModel
from edu_exam_agent.ui.pages.question_bank_page import QuestionBankPage


def _question(course_id: int, index: int) -> QuestionModel:
    return QuestionModel(
        course_id=course_id,
        question_type="填空题",
        stem=f"定位测试题 {index}",
        options_json="[]",
        answer=str(index),
        analysis="测试解析",
        scoring_criteria="正确得 5 分",
        knowledge_points_json='["定位测试"]',
        difficulty=3,
        estimated_time_minutes=2,
        score=5,
        quality_score=0.9,
        recommendation_score=90,
        boundary_passed=True,
        status="validated",
        generation_model="mock",
    )


def test_focus_generated_questions_selects_every_requested_row(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    engine = create_database_engine(tmp_path / "question-bank-navigation.db")
    initialize_database(engine)
    courses = CourseService(engine)
    course = courses.create(CourseInput(name="八年级数学"))
    with Session(engine) as session, session.begin():
        session.add_all((_question(course.id, 1), _question(course.id, 2)))

    page = QuestionBankPage(courses, QuestionBankService(engine))
    ids = [question.id for question in page._questions]
    page.focus_question_ids(ids)
    application.processEvents()

    selected_rows = {
        index.row() for index in page.table.selectionModel().selectedRows()
    }
    assert selected_rows == {0, 1}
    assert page.table.currentRow() == 0
    assert "已定位本次生成的 2 道题" == page.status_label.text()
    page.close()
