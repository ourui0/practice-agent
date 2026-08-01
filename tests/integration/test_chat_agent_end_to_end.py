from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from edu_exam_agent.application.agent_tools import (
    AgentToolRegistry,
    TaskControlRegistry,
    ToolExecutionContext,
)
from edu_exam_agent.application.services.chat_agent_service import ChatAgentService
from edu_exam_agent.application.services.chat_service import ChatService
from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.knowledge_point_service import KnowledgePointService
from edu_exam_agent.application.services.paper_service import PaperService
from edu_exam_agent.application.services.provider_service import ProviderConfig
from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import (
    AgentOperationModel,
    KnowledgePointModel,
    PaperHistoryModel,
)
from edu_exam_agent.infrastructure.llm.provider import AssistantToolResponse, ToolCall
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


class EndToEndProvider:
    def __init__(self, course_id: int, document_id: int, chapter_id: int) -> None:
        self.tool_responses = [
            AssistantToolResponse(
                "", (ToolCall("courses", "list_courses", {}),)
            ),
            AssistantToolResponse(
                "",
                (
                    ToolCall(
                        "books",
                        "list_textbooks",
                        {"course_id": course_id},
                    ),
                ),
            ),
            AssistantToolResponse(
                "",
                (
                    ToolCall(
                        "chapters",
                        "list_chapters",
                        {"course_id": course_id, "document_id": document_id},
                    ),
                ),
            ),
            AssistantToolResponse(
                "",
                (
                    ToolCall(
                        "plan",
                        "prepare_generation_plan",
                        {
                            "course_id": course_id,
                            "document_id": document_id,
                            "chapter_ids": [chapter_id],
                            "difficulty": 2,
                            "question_type_counts": {"填空题": 1},
                            "title": "一次函数智能体训练",
                            "assemble_paper": True,
                            "export_word": True,
                        },
                    ),
                ),
            ),
        ]

    def chat_with_tools(self, messages, tools):
        return self.tool_responses.pop(0)

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        return {
            "question_type": "填空题",
            "stem": "若函数 y=(m-2)x+1 是一次函数，则 m 应满足______。",
            "options": [],
            "answer": "m≠2",
            "analysis": "一次函数中自变量系数不能为0，所以m-2≠0，得到m≠2。",
            "scoring_criteria": "正确写出m≠2得5分",
            "knowledge_points": ["一次函数"],
            "difficulty": 2,
            "estimated_time_minutes": 2,
            "score": 5,
            "diagram": None,
        }


class EndToEndProviders:
    def __init__(self, provider: EndToEndProvider) -> None:
        self.provider = provider

    def get_default(self):
        return ProviderConfig("测试模型", "https://example.test", "mock-tool-model", True)

    def create_provider(self):
        return self.provider, "mock-tool-model"


def test_confirmed_chat_plan_really_generates_assembles_and_exports(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "agent-e2e.db")
    initialize_database(engine)
    courses = CourseService(engine)
    documents = DocumentService(engine)
    knowledge = KnowledgePointService(engine)
    bank = QuestionBankService(engine)
    papers = PaperService(bank)
    course = courses.create(CourseInput(name="沪科版八年级上册数学"))
    material = tmp_path / "八年级上册数学.md"
    material.write_text(
        "# 第12章 一次函数\n一次函数的一般形式是 y=kx+b，其中k不等于0。",
        encoding="utf-8",
    )
    document = documents.import_document(course.id, material)
    chapter = documents.list_chapters(document.id)[0]
    with Session(engine) as session:
        session.add(
            KnowledgePointModel(
                course_id=course.id,
                chapter_id=chapter.id,
                name="一次函数",
                status="confirmed",
                is_enabled=True,
            )
        )
        session.commit()

    provider = EndToEndProvider(course.id, document.id, chapter.id)
    providers = EndToEndProviders(provider)
    context = ToolExecutionContext(
        engine=engine,
        courses=courses,
        documents=documents,
        knowledge_points=knowledge,
        bank=bank,
        papers=papers,
        providers=providers,  # type: ignore[arg-type]
        retriever=FtsRetriever(engine),
        output_dir=tmp_path / "exports",
        task_controls=TaskControlRegistry(),
    )
    registry = AgentToolRegistry(context)
    chat = ChatService(engine, providers)  # type: ignore[arg-type]
    agent = ChatAgentService(
        engine,
        providers,  # type: ignore[arg-type]
        chat,
        registry,
        context,
    )
    conversation = chat.create_conversation()

    planned = agent.send_message(
        conversation.id,
        "请生成一道一次函数填空题，难度2，组卷并导出Word。",
    )
    completed = agent.confirm_plan(conversation.id, planned.event_ids[0])

    questions = bank.list(course_id=course.id)
    assert len(questions) == 1
    assert questions[0].stem.startswith("若函数")
    with Session(engine) as session:
        paper = session.scalar(select(PaperHistoryModel))
        assert paper is not None
        assert paper.status == "exported"
        generation_operation = session.scalar(
            select(AgentOperationModel).where(
                AgentOperationModel.tool_name == "generate_single_question"
            )
        )
        assert generation_operation is not None
        assert generation_operation.status == "completed"
    outputs = list((tmp_path / "exports").glob("*.docx"))
    assert len(outputs) == 1
    assert outputs[0].stat().st_size > 1_000
    assert "Word 已导出" in completed.content
