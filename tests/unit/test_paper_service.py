from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document as WordDocument
from sqlalchemy.orm import Session

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.paper_service import PaperRequest, PaperService
from edu_exam_agent.application.services.question_agent import (
    GenerationRequest,
    QuestionGenerationAgent,
)
from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import PaperHistoryModel, QuestionModel
from edu_exam_agent.infrastructure.llm import MockProvider
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


def _question(
    course_id: int,
    index: int,
    difficulty: int = 3,
    question_type: str = "填空题",
) -> QuestionModel:
    return QuestionModel(
        course_id=course_id,
        question_type=question_type,
        stem=f"测试题干 {index} 是什么？",
        options_json="[]",
        answer=f"答案 {index}",
        analysis=f"这是第 {index} 题的完整解析。",
        scoring_criteria="答对得 5 分",
        knowledge_points_json='["测试知识点"]',
        difficulty=difficulty,
        estimated_time_minutes=2,
        score=5,
        quality_score=0.9,
        recommendation_score=90 - index,
        boundary_passed=True,
        status="validated",
        generation_model="mock",
    )


def test_assemble_preview_and_export(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "paper.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    with Session(engine) as session, session.begin():
        session.add_all((_question(course.id, 1, 2), _question(course.id, 2, 3)))

    service = PaperService(QuestionBankService(engine))
    paper = service.assemble(
        PaperRequest(course.id, "单元测试", ("填空题",), 2, target_difficulty=3)
    )
    assert len(paper.questions) == 2
    assert paper.questions[0].difficulty == 3
    assert paper.total_score == 10
    assert "答案 1" not in service.preview(paper)

    output = service.export_docx(paper, tmp_path / "单元测试.docx")
    assert output.exists()
    assert output.stat().st_size > 1000


def test_assemble_rejects_shortage_and_invalid_request(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "paper.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    service = PaperService(QuestionBankService(engine))

    with pytest.raises(ValueError, match="至少选择"):
        service.assemble(PaperRequest(course.id, "练习", (), 1))
    with pytest.raises(ValueError, match="只有 0 道"):
        service.assemble(PaperRequest(course.id, "练习", ("填空题",), 1))


def test_assemble_filters_by_document_and_chapter(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "scope.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    documents = DocumentService(engine)
    first_file = tmp_path / "函数.md"
    first_file.write_text("# 一次函数\n一次函数的形式是 y=kx+b。", encoding="utf-8")
    second_file = tmp_path / "几何.md"
    second_file.write_text("# 全等三角形\n全等三角形的对应边相等。", encoding="utf-8")
    first_document = documents.import_document(course.id, first_file)
    second_document = documents.import_document(course.id, second_file)

    def generate(point: str, answer: str) -> None:
        response = {
            "question_type": "填空题",
            "stem": f"请填写关于{point}的正确结论。",
            "options": [],
            "answer": answer,
            "analysis": f"依据教材中{point}的定义作答。",
            "scoring_criteria": "正确得5分",
            "knowledge_points": [point],
            "difficulty": 2,
            "estimated_time_minutes": 2,
            "score": 5,
        }
        QuestionGenerationAgent(
            engine, FtsRetriever(engine), MockProvider(response), "mock"
        ).generate(GenerationRequest(course.id, point, "填空题", 2))

    generate("一次函数", "y=kx+b")
    generate("全等三角形", "对应边相等")
    service = PaperService(QuestionBankService(engine))
    first_chapter = documents.list_chapters(first_document.id)[0]

    by_document = service.assemble(
        PaperRequest(
            course.id,
            "函数练习",
            ("填空题",),
            1,
            document_id=first_document.id,
        )
    )
    assert "一次函数" in by_document.questions[0].stem
    by_chapter = service.assemble(
        PaperRequest(
            course.id,
            "章节练习",
            ("填空题",),
            1,
            document_id=first_document.id,
            chapter_ids=(first_chapter.id,),
        )
    )
    assert by_chapter.questions[0].id == by_document.questions[0].id
    with pytest.raises(ValueError, match="只有 0 道"):
        service.assemble(
            PaperRequest(
                course.id,
                "错误范围",
                ("填空题",),
                1,
                document_id=second_document.id,
                chapter_ids=(first_chapter.id,),
            )
        )


def test_assemble_honors_type_quotas_and_canonical_order(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "quota.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    types = (
        "应用题",
        "填空题",
        "单项选择题",
        "计算题",
        "单项选择题",
        "计算题",
    )
    with Session(engine) as session, session.begin():
        session.add_all(
            _question(course.id, index, question_type=question_type)
            for index, question_type in enumerate(types, 1)
        )

    request = PaperRequest(
        course.id,
        "配额试卷",
        ("单项选择题", "填空题", "计算题", "应用题"),
        6,
        target_difficulty=3,
        question_type_counts=(
            ("应用题", 1),
            ("计算题", 2),
            ("单项选择题", 2),
            ("填空题", 1),
        ),
    )
    service = PaperService(QuestionBankService(engine))
    paper = service.assemble(request)

    assert [question.question_type for question in paper.questions] == [
        "单项选择题",
        "单项选择题",
        "填空题",
        "计算题",
        "计算题",
        "应用题",
    ]
    assert service.available_count_by_type(request) == {
        "单项选择题": 2,
        "填空题": 1,
        "计算题": 2,
        "应用题": 1,
    }
    preview = service.preview(paper)
    assert preview.index("一、选择题") < preview.index("二、填空题")
    assert preview.index("二、填空题") < preview.index("三、计算题")
    assert preview.index("三、计算题") < preview.index("四、应用题")
    output = service.export_docx(paper, tmp_path / "配额试卷.docx")
    paragraphs = [paragraph.text for paragraph in WordDocument(output).paragraphs]
    choice_heading = next(index for index, text in enumerate(paragraphs) if "一、选择题" in text)
    fill_heading = next(index for index, text in enumerate(paragraphs) if "二、填空题" in text)
    calculation_heading = next(
        index for index, text in enumerate(paragraphs) if "三、计算题" in text
    )
    application_heading = next(
        index for index, text in enumerate(paragraphs) if "四、应用题" in text
    )
    assert choice_heading < fill_heading < calculation_heading < application_heading
    assert any(text.startswith("1. 答案：") for text in paragraphs)
    assert any(text.startswith("6. 答案：") for text in paragraphs)


def test_quota_shortage_is_reported_even_when_total_is_sufficient(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "quota-shortage.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                *(
                    _question(course.id, index, question_type="单项选择题")
                    for index in range(1, 5)
                ),
                _question(course.id, 5, question_type="应用题"),
            ]
        )

    request = PaperRequest(
        course.id,
        "题型不足",
        ("单项选择题", "应用题"),
        4,
        question_type_counts=(("单项选择题", 2), ("应用题", 2)),
    )
    with pytest.raises(ValueError, match="应用题需要2道.*还缺1道"):
        PaperService(QuestionBankService(engine)).assemble(request)


def test_type_quota_validation_rejects_invalid_configurations() -> None:
    with pytest.raises(ValueError, match="重复题型"):
        PaperRequest(
            1,
            "重复",
            ("填空题",),
            2,
            question_type_counts=(("填空题", 1), ("填空题", 1)),
        ).validate()
    with pytest.raises(ValueError, match="不支持的题型"):
        PaperRequest(
            1,
            "未知",
            ("简答题",),
            1,
            question_type_counts=(("简答题", 1),),
        ).validate()
    with pytest.raises(ValueError, match="题型数量之和"):
        PaperRequest(
            1,
            "不一致",
            ("填空题",),
            2,
            question_type_counts=(("填空题", 1),),
        ).validate()


def test_legacy_request_remains_supported_and_is_type_sorted(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "legacy-order.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    with Session(engine) as session, session.begin():
        session.add_all(
            _question(course.id, index, question_type=question_type)
            for index, question_type in enumerate(
                ("应用题", "计算题", "填空题", "单项选择题"), 1
            )
        )
    paper = PaperService(QuestionBankService(engine)).assemble(
        PaperRequest(
            course.id,
            "旧版请求",
            ("单项选择题", "填空题", "计算题", "应用题"),
            4,
        )
    )
    assert [question.question_type for question in paper.questions] == [
        "单项选择题",
        "填空题",
        "计算题",
        "应用题",
    ]


def test_exported_paper_questions_are_excluded_from_recent_selection(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "paper-history.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    with Session(engine) as session, session.begin():
        session.add_all((_question(course.id, 1), _question(course.id, 2)))
    service = PaperService(QuestionBankService(engine))
    request = PaperRequest(course.id, "第一次练习", ("填空题",), 1)

    first = service.assemble(request)
    assert first.history_id is not None
    first_id = first.questions[0].id
    service.export_docx(first, tmp_path / "第一次练习.docx")
    second = service.assemble(
        PaperRequest(course.id, "第二次练习", ("填空题",), 1)
    )
    assert second.questions[0].id != first_id
    reusable = service.assemble(
        PaperRequest(
            course.id,
            "允许复用",
            ("填空题",),
            1,
            exclude_recent_days=0,
            exclude_recent_papers=0,
        )
    )
    assert reusable.questions[0].id == first_id
    with Session(engine) as session:
        history = session.get(PaperHistoryModel, first.history_id)
        assert history is not None and history.status == "exported"
