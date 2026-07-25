from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.paper_service import PaperRequest, PaperService
from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.application.services.question_types import QUESTION_TYPE_ORDER
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import QuestionModel


DATASET = Path(__file__).parents[1] / "fixtures" / "question_type_quota_blackbox.json"


def _question(course_id: int, question_type: str, index: int) -> QuestionModel:
    return QuestionModel(
        course_id=course_id,
        question_type=question_type,
        stem=f"{question_type}黑盒题目{index}",
        options_json="[]",
        answer="答案",
        analysis="用于验证题型配额和稳定排列顺序。",
        scoring_criteria="正确得5分",
        knowledge_points_json='["黑盒知识点"]',
        difficulty=3,
        estimated_time_minutes=3,
        score=5,
        quality_score=90,
        recommendation_score=90 - index / 100,
        boundary_passed=True,
        status="validated",
        generation_model="blackbox",
    )


def test_question_type_quota_blackbox_dataset(tmp_path: Path) -> None:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    for case_index, case in enumerate(cases):
        engine = create_database_engine(tmp_path / f"quota-{case_index}.db")
        initialize_database(engine)
        course = CourseService(engine).create(CourseInput(name=case["name"]))
        counts = case["counts"]
        with Session(engine) as session, session.begin():
            for question_type in QUESTION_TYPE_ORDER:
                for index in range(counts[question_type] + 1):
                    session.add(_question(course.id, question_type, index))

        positive_counts = tuple(
            (question_type, counts[question_type])
            for question_type in QUESTION_TYPE_ORDER
            if counts[question_type] > 0
        )
        request = PaperRequest(
            course_id=course.id,
            title=case["name"],
            question_types=tuple(item[0] for item in positive_counts),
            count=case["expected_total"],
            question_type_counts=positive_counts,
        )
        service = PaperService(QuestionBankService(engine))
        paper = service.assemble(request)
        actual_order = [question.question_type for question in paper.questions]
        expected_order = case.get("expected_order") or [
            question_type
            for question_type in QUESTION_TYPE_ORDER
            for _ in range(counts[question_type])
        ]

        assert len(paper.questions) == case["expected_total"]
        assert actual_order == expected_order
        preview = service.preview(paper)
        if counts["填空题"] == 0:
            assert "、填空题（共" not in preview
