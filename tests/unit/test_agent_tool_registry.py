from __future__ import annotations

from sqlalchemy.orm import Session

from edu_exam_agent.application.agent_tools import (
    AgentToolRegistry,
    TaskControlRegistry,
    ToolExecutionContext,
)
from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.knowledge_point_service import (
    KnowledgePointInput,
    KnowledgePointService,
)
from edu_exam_agent.application.services.paper_service import PaperService
from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import AgentOperationModel
from edu_exam_agent.infrastructure.llm.provider import ToolCall
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


class _Providers:
    def create_provider(self):
        raise AssertionError("read-only registry test must not call a model")


def _registry(tmp_path):
    engine = create_database_engine(tmp_path / "tools.db")
    initialize_database(engine)
    courses = CourseService(engine)
    documents = DocumentService(engine)
    knowledge = KnowledgePointService(engine)
    bank = QuestionBankService(engine)
    context = ToolExecutionContext(
        engine=engine,
        courses=courses,
        documents=documents,
        knowledge_points=knowledge,
        bank=bank,
        papers=PaperService(bank),
        providers=_Providers(),  # type: ignore[arg-type]
        retriever=FtsRetriever(engine),
        output_dir=tmp_path / "exports",
        task_controls=TaskControlRegistry(),
    )
    return engine, context, AgentToolRegistry(context)


def test_registry_is_whitelisted_and_rejects_extra_arguments(tmp_path) -> None:
    _engine, _context, registry = _registry(tmp_path)
    names = {tool.name for tool in registry.definitions()}
    assert {
        "list_courses",
        "list_textbooks",
        "list_chapters",
        "list_knowledge_points",
        "inspect_question_inventory",
        "prepare_generation_plan",
        "generate_single_question",
        "generate_question_batch",
        "assemble_paper",
        "export_paper_word",
    } <= names
    assert not registry.execute(ToolCall("x", "run_python", {})).succeeded
    invalid = registry.execute(
        ToolCall("x2", "list_courses", {"sql": "DROP TABLE courses"})
    )
    assert not invalid.succeeded
    assert "参数不合法" in invalid.user_message


def test_read_tools_return_only_safe_fields_and_prepare_valid_plan(tmp_path) -> None:
    _engine, context, registry = _registry(tmp_path)
    course = context.courses.create(
        CourseInput(
            name="沪科版八年级上册数学",
            grade="八年级",
            semester="上册",
            textbook_version="沪科版",
        )
    )
    material = tmp_path / "八年级上册数学.md"
    material.write_text(
        "# 第12章 一次函数\n## 12.1 函数\n一次函数的基本概念。",
        encoding="utf-8",
    )
    document = context.documents.import_document(course.id, material)
    context.knowledge_points.create_manual(
        course.id,
        KnowledgePointInput(name="一次函数"),
    )

    textbooks = registry.execute(
        ToolCall("books", "list_textbooks", {"course_id": course.id})
    )
    assert textbooks.succeeded
    assert "original_path" not in str(textbooks.content)
    plan = registry.execute(
        ToolCall(
            "plan",
            "prepare_generation_plan",
            {
                "course_id": course.id,
                "document_id": document.id,
                "difficulty": 4,
                "question_type_counts": {
                    "选择题": 1,
                    "填空题": 1,
                },
                "title": "一次函数训练",
            },
        )
    )
    assert plan.succeeded
    assert plan.content["total_count"] == 2
    assert plan.content["question_type_counts"] == {
        "单项选择题": 1,
        "填空题": 1,
    }
    assert plan.content["knowledge_points"] == ["一次函数"]


def test_mutating_tools_require_confirmation_and_are_idempotent(tmp_path) -> None:
    engine, context, registry = _registry(tmp_path)
    call = ToolCall(
        "cancel",
        "cancel_generation_task",
        {
            "operation_id": "operation-cancel-1",
            "task_id": "generation-task-1",
        },
    )
    denied = registry.execute(call)
    assert not denied.succeeded
    assert "确认" in denied.user_message

    context.allow_mutations = True
    first = registry.execute(call, context)
    second = registry.execute(call, context)
    assert first.succeeded and second.succeeded
    assert second.user_message.startswith("已返回")
    with Session(engine) as session:
        operations = session.query(AgentOperationModel).all()
    assert len(operations) == 1
