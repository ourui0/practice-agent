from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.question_agent import (
    GenerationRequest,
    QuestionGenerationAgent,
)
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import (
    QuestionFigureModel,
    QuestionModel,
    QuestionSourceModel,
    QuestionValidationModel,
)
from edu_exam_agent.infrastructure.llm import MockProvider
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


def test_grounded_question_is_validated_scored_and_saved(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "questions.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    material = tmp_path / "教材.md"
    material.write_text(
        "# 12.2 一次函数\n一次函数的一般形式是 y=kx+b，其中k不等于0。", encoding="utf-8"
    )
    DocumentService(engine).import_document(course.id, material)
    response = {
        "question_type": "单项选择题",
        "stem": "下列函数中，属于一次函数的是（ ）。",
        "options": [
            {"label": "A", "content": "y=2x+1"},
            {"label": "B", "content": "y=x²"},
            {"label": "C", "content": "y=1/x"},
            {"label": "D", "content": "y=3"},
        ],
        "answer": "A",
        "analysis": "y=2x+1符合y=kx+b且k不等于0。",
        "scoring_criteria": "选择A得5分。",
        "knowledge_points": ["一次函数"],
        "difficulty": 2,
        "estimated_time_minutes": 2,
        "score": 5,
    }
    agent = QuestionGenerationAgent(engine, FtsRetriever(engine), MockProvider(response), "mock")
    result = agent.generate(GenerationRequest(course.id, "一次函数", "单项选择题", 2))
    assert result.boundary_passed
    assert not result.issues
    assert 0.5 < result.quality_score < 1
    assert 50 < result.recommendation_score < 100
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(QuestionModel)) == 1
        assert session.scalar(select(func.count()).select_from(QuestionSourceModel)) >= 1
        validation = session.scalar(select(QuestionValidationModel))
        assert validation is not None and validation.passed


def test_strict_mode_refuses_generation_without_evidence(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "strict.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    agent = QuestionGenerationAgent(engine, FtsRetriever(engine), MockProvider({}), "mock")
    try:
        agent.generate(GenerationRequest(course.id, "不存在的知识点", "填空题", 2))
    except ValueError as exc:
        assert "教材依据" in str(exc)
    else:
        raise AssertionError("严格教材模式必须拒绝无依据生成")


def test_scoped_generation_uses_chapter_context_when_title_phrase_is_not_indexed(
    tmp_path,
) -> None:
    engine = create_database_engine(tmp_path / "scope_fallback.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    material = tmp_path / "教材.md"
    material.write_text("# 6.1 平方根\n正数有两个平方根，它们互为相反数。", encoding="utf-8")
    document = DocumentService(engine).import_document(course.id, material)
    chapter = DocumentService(engine).list_chapters(document.id)[0]
    response = {
        "question_type": "填空题",
        "stem": "正数的两个平方根互为______。",
        "options": [],
        "answer": "相反数",
        "analysis": "依据教材中的平方根性质可得。",
        "scoring_criteria": "正确得5分",
        "knowledge_points": ["教材标题文本层缺失的知识点"],
        "difficulty": 2,
        "estimated_time_minutes": 2,
        "score": 5,
    }
    result = QuestionGenerationAgent(
        engine, FtsRetriever(engine), MockProvider(response), "mock"
    ).generate(
        GenerationRequest(
            course.id,
            "教材标题文本层缺失的知识点",
            "填空题",
            2,
            document_id=document.id,
            chapter_ids=(chapter.id,),
        )
    )
    assert result.evidence
    assert result.evidence[0].chapter_id == chapter.id


def test_generation_retries_when_question_references_missing_figure(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "figure_retry.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    material = tmp_path / "教材.md"
    material.write_text("# 1.1 平行线\n平行线的同位角相等。", encoding="utf-8")
    DocumentService(engine).import_document(course.id, material)
    base = {
        "question_type": "填空题",
        "options": [],
        "answer": "相等",
        "analysis": "根据平行线的性质可得结论。",
        "scoring_criteria": "正确得5分",
        "knowledge_points": ["平行线"],
        "difficulty": 2,
        "estimated_time_minutes": 2,
        "score": 5,
    }

    class SequenceProvider:
        def __init__(self):
            self.calls = 0

        def generate_json(self, system_prompt, user_prompt):
            self.calls += 1
            stem = (
                "如图，两条平行线的同位角______。"
                if self.calls == 1
                else "两条平行线被第三条直线所截，同位角______。"
            )
            return {**base, "stem": stem}

    provider = SequenceProvider()
    result = QuestionGenerationAgent(
        engine, FtsRetriever(engine), provider, "mock"
    ).generate(GenerationRequest(course.id, "平行线", "填空题", 2))
    assert provider.calls == 2
    assert "如图" not in result.question.stem


def test_generation_saves_diagram_for_figure_question(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "diagram.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    material = tmp_path / "教材.md"
    material.write_text("# 1.1 三角形\n三角形由三条线段首尾相接组成。", encoding="utf-8")
    DocumentService(engine).import_document(course.id, material)
    response = {
        "question_type": "单项选择题",
        "stem": "如图，三角形ABC中最长的边是（ ）。",
        "options": ["A. AB", "B. BC", "C. AC", "D. 无法判断"],
        "answer": "A",
        "analysis": "根据配图中各点的位置判断。",
        "scoring_criteria": "选择A得5分",
        "knowledge_points": ["三角形"],
        "difficulty": 2,
        "estimated_time_minutes": 2,
        "score": 5,
        "diagram": {
            "kind": "geometry",
            "points": [
                {"label": "A", "x": 0, "y": 0},
                {"label": "B", "x": 5, "y": 0},
                {"label": "C", "x": 2, "y": 2},
            ],
            "segments": [
                {"start": "A", "end": "B"},
                {"start": "B", "end": "C"},
                {"start": "C", "end": "A"},
            ],
        },
    }
    result = QuestionGenerationAgent(
        engine, FtsRetriever(engine), MockProvider(response), "mock"
    ).generate(GenerationRequest(course.id, "三角形", "单项选择题", 2))
    assert result.figure_png and result.figure_png.startswith(b"\x89PNG")
    with Session(engine) as session:
        figure = session.scalar(select(QuestionFigureModel))
        assert figure is not None and figure.png_data.startswith(b"\x89PNG")
