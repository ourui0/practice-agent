from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.question_similarity import (
    QuestionSimilarityService,
    build_fingerprint,
    compare_fingerprints,
    extract_model_tags,
)
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import (
    QuestionDuplicateRelationModel,
    QuestionFingerprintModel,
    QuestionModel,
)


def _question(course_id: int, stem: str, index: int) -> QuestionModel:
    return QuestionModel(
        course_id=course_id,
        question_type="计算题",
        stem=stem,
        options_json="[]",
        answer="答案",
        analysis="连接辅助线，因为条件成立，所以由勾股定理可得答案。",
        scoring_criteria="过程正确得满分",
        knowledge_points_json='["四边形", "勾股定理"]',
        difficulty=4,
        estimated_time_minutes=8,
        score=10,
        quality_score=0.9,
        recommendation_score=90 - index,
        boundary_passed=True,
        status="validated",
        generation_model="test",
    )


def test_number_and_vertex_only_variants_are_duplicates() -> None:
    first = build_fingerprint(
        "矩形ABCD中AB=6，点E在BC上，求AE。", "由勾股定理计算。", ["矩形"], "计算题"
    )
    second = build_fingerprint(
        "矩形PQRS中PQ=15，点M在QR上，求PM。", "由勾股定理计算。", ["矩形"], "计算题"
    )
    result = compare_fingerprints(first, second)
    assert result.level == "duplicate"
    assert result.total == 1


def test_mother_model_tags_are_multi_label_and_explainable() -> None:
    tags = extract_model_tags(
        "矩形中有一动点，求面积最小值并分类讨论参数m。",
        "作辅助线后建立方程，再分情况筛选取值范围。",
    )
    assert {"动点模型", "面积最值", "参数分类", "辅助线构造", "方程建模"} <= set(tags)


def test_backfill_persists_fingerprints_without_disabling_history(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "similarity.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    with Session(engine) as session, session.begin():
        session.add_all(
            (
                _question(course.id, "矩形ABCD中AB=6，点E在BC上，求AE。", 1),
                _question(course.id, "矩形PQRS中PQ=15，点M在QR上，求PM。", 2),
            )
        )

    questions, relations = QuestionSimilarityService(engine).backfill(course.id)
    assert questions == 2
    assert relations >= 2
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(QuestionFingerprintModel)) == 2
        assert (
            session.scalar(select(func.count()).select_from(QuestionDuplicateRelationModel))
            >= 2
        )
        assert set(session.scalars(select(QuestionModel.status))) == {"validated"}
