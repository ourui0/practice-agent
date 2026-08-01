from __future__ import annotations

from types import SimpleNamespace

import pytest

from edu_exam_agent.application.agent_tools import (
    TaskControlRegistry,
    ToolExecutionContext,
)
from edu_exam_agent.application.agent_tools.schemas import ToolResult
from edu_exam_agent.application.services.chat_agent_service import ChatAgentService
from edu_exam_agent.application.services.chat_service import ChatService, ChatServiceError
from edu_exam_agent.application.services.provider_service import ProviderConfig
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.llm.provider import (
    AssistantToolResponse,
    ToolCall,
    ToolDefinition,
)

PLAN = {
    "course_id": 1,
    "document_id": 2,
    "chapter_ids": [3],
    "chapter_query": "",
    "knowledge_point_ids": [],
    "difficulty": 4,
    "question_type_counts": {"单项选择题": 1, "填空题": 1},
    "total_count": 2,
    "title": "一次函数训练",
    "exclude_recent": True,
    "allow_ai_backfill": True,
    "include_answers": True,
    "estimated_duration_minutes": 30,
    "assemble_paper": True,
    "export_word": True,
    "course_name": "八年级上册数学",
    "document_name": "教材.pdf",
    "chapter_names": ["第12章 一次函数"],
    "knowledge_points": ["一次函数"],
}


class _Provider:
    def __init__(self):
        self.responses = [
            AssistantToolResponse(
                "",
                (ToolCall("courses", "list_courses", {}),),
            ),
            AssistantToolResponse(
                "",
                (
                    ToolCall(
                        "plan",
                        "prepare_generation_plan",
                        {
                            "course_id": 1,
                            "document_id": 2,
                            "difficulty": 4,
                            "question_type_counts": {"选择题": 1, "填空题": 1},
                        },
                    ),
                ),
            ),
        ]
        self.requests = []
        self.chat_requests = []
        self.chat_responses = ["普通问答回复"]

    def chat_with_tools(self, messages, tools):
        self.requests.append(messages)
        return self.responses.pop(0)

    def chat(self, messages):
        self.chat_requests.append(messages)
        return self.chat_responses.pop(0)


class _Providers:
    def __init__(self, provider):
        self.provider = provider

    def get_default(self):
        return ProviderConfig("测试", "https://example.test", "tool-model", True)

    def create_provider(self):
        return self.provider, "tool-model"


class _Registry:
    def __init__(self):
        self.calls = []

    def definitions(self):
        return [
            ToolDefinition(
                "list_courses",
                "查询课程",
                {"type": "object", "properties": {}},
            ),
            ToolDefinition(
                "prepare_generation_plan",
                "准备计划",
                {"type": "object", "properties": {}},
            ),
        ]

    def execute(self, call, context=None):
        self.calls.append((call, context))
        if call.name == "list_courses":
            return ToolResult(call.id, call.name, True, {"courses": [{"id": 1}]})
        if call.name == "prepare_generation_plan":
            return ToolResult(call.id, call.name, True, PLAN)
        if call.name == "generate_question_batch":
            return ToolResult(
                call.id,
                call.name,
                True,
                {
                    "target_count": 2,
                    "qualified_count": 2,
                    "question_ids": [10, 11],
                    "question_type_counts": {"单项选择题": 1, "填空题": 1},
                    "rejected_duplicate_count": 0,
                    "rejected_difficulty_count": 0,
                    "operation_id": call.arguments["operation_id"],
                },
            )
        if call.name == "assemble_paper":
            return ToolResult(
                call.id,
                call.name,
                True,
                {
                    "paper_id": 20,
                    "question_count": 2,
                    "total_score": 10,
                    "duration_minutes": 30,
                    "operation_id": call.arguments["operation_id"],
                },
            )
        if call.name == "export_paper_word":
            return ToolResult(
                call.id,
                call.name,
                True,
                {
                    "filename": "一次函数训练.docx",
                    "question_count": 2,
                    "include_answers": True,
                    "operation_id": call.arguments["operation_id"],
                },
            )
        raise AssertionError(call.name)

    def resolve_local_path(self, operation_id):
        return None


def _service(tmp_path):
    engine = create_database_engine(tmp_path / "agent.db")
    initialize_database(engine)
    provider = _Provider()
    providers = _Providers(provider)
    chat = ChatService(engine, providers)  # type: ignore[arg-type]
    registry = _Registry()
    context = ToolExecutionContext(
        engine=engine,
        courses=SimpleNamespace(),
        documents=SimpleNamespace(),
        knowledge_points=SimpleNamespace(),
        bank=SimpleNamespace(),
        papers=SimpleNamespace(),
        providers=providers,  # type: ignore[arg-type]
        retriever=SimpleNamespace(),
        output_dir=tmp_path,
        task_controls=TaskControlRegistry(),
    )
    service = ChatAgentService(
        engine,
        providers,  # type: ignore[arg-type]
        chat,
        registry,  # type: ignore[arg-type]
        context,
    )
    return service, chat, provider, registry


def test_agent_executes_read_tools_then_persists_confirmation_plan(tmp_path) -> None:
    service, chat, provider, registry = _service(tmp_path)
    conversation = chat.create_conversation()

    result = service.send_message(
        conversation.id,
        "请生成一次函数难度4的选择题1道、填空题1道",
    )

    assert result.event_ids
    events = service.list_events(conversation.id)
    assert len(events) == 1
    assert events[0].kind == "plan"
    assert events[0].status == "pending"
    assert [call.name for call, _context in registry.calls] == [
        "list_courses",
        "prepare_generation_plan",
    ]
    assert provider.requests[1][-1].role == "tool"
    assert "确认" in result.content


def test_confirmed_plan_runs_real_tool_sequence_and_persists_cards(tmp_path) -> None:
    service, chat, _provider, registry = _service(tmp_path)
    conversation = chat.create_conversation()
    plan_result = service.send_message(
        conversation.id,
        "请生成一次函数难度4的选择题1道、填空题1道",
    )

    result = service.confirm_plan(
        conversation.id,
        plan_result.event_ids[0],
    )

    names = [call.name for call, _context in registry.calls]
    assert names[-3:] == [
        "generate_question_batch",
        "assemble_paper",
        "export_paper_word",
    ]
    events = service.list_events(conversation.id)
    assert [event.kind for event in events] == [
        "plan",
        "generation",
        "paper",
        "export",
    ]
    assert all(event.status == "completed" for event in events)
    assert "Word 已导出" in result.content


def test_agent_stops_repeated_tool_loop_after_eight_steps(tmp_path) -> None:
    service, chat, provider, _registry = _service(tmp_path)
    provider.responses = [
        AssistantToolResponse(
            "",
            (ToolCall(f"repeat-{index}", "list_courses", {}),),
        )
        for index in range(8)
    ]
    conversation = chat.create_conversation()

    with pytest.raises(ChatServiceError, match="步骤过多"):
        service.send_message(conversation.id, "请查询课程并生成练习题")


def test_follow_up_start_message_points_to_pending_confirmation(tmp_path) -> None:
    service, chat, provider, _registry = _service(tmp_path)
    conversation = chat.create_conversation()
    service.send_message(
        conversation.id,
        "请生成一次函数难度4的选择题1道、填空题1道",
    )

    result = service.send_message(conversation.id, "请你开始")

    assert "确认执行" in result.content
    assert len(provider.requests) == 2


def test_follow_up_start_continues_when_plan_is_not_ready(tmp_path) -> None:
    service, chat, provider, _registry = _service(tmp_path)
    conversation = chat.create_conversation()
    provider.responses = [
        AssistantToolResponse(
            "",
            (ToolCall("courses-first", "list_courses", {}),),
        ),
        AssistantToolResponse("请确认难度？", ()),
    ]
    first = service.send_message(conversation.id, "请生成一次函数练习题")
    assert "难度" in first.content
    assert not first.event_ids
    provider.responses = [
        AssistantToolResponse(
            "",
            (ToolCall("courses-second", "list_courses", {}),),
        ),
        AssistantToolResponse(
            "",
            (
                ToolCall(
                    "plan-second",
                    "prepare_generation_plan",
                    {
                        "course_id": 1,
                        "document_id": 2,
                        "difficulty": 4,
                        "question_type_counts": {"选择题": 1, "填空题": 1},
                    },
                ),
            ),
        ),
    ]

    result = service.send_message(conversation.id, "请你开始")

    assert result.event_ids
    assert len(provider.requests) == 4


def test_common_single_question_wording_enters_tool_agent(tmp_path) -> None:
    service, chat, provider, _registry = _service(tmp_path)
    conversation = chat.create_conversation()

    result = service.send_message(conversation.id, "请帮我出一道选择题")

    assert result.event_ids
    assert len(provider.requests) == 2


def test_tool_task_rejects_direct_fake_generation_without_tool_calls(tmp_path) -> None:
    service, chat, provider, _registry = _service(tmp_path)
    conversation = chat.create_conversation()
    fake_result = "下面是已生成的题目：\n" + "\n".join(
        f"{index}. 模拟题目" for index in range(1, 80)
    )
    provider.responses = [
        AssistantToolResponse(fake_result, ()),
        AssistantToolResponse(fake_result, ()),
    ]

    with pytest.raises(ChatServiceError, match="未按要求调用程序工具"):
        service.send_message(conversation.id, "请生成一次函数练习题")

    assert service.list_events(conversation.id) == []


def test_ordinary_question_resets_previous_tool_context(tmp_path) -> None:
    service, chat, provider, _registry = _service(tmp_path)
    conversation = chat.create_conversation()
    service.send_message(
        conversation.id,
        "请生成一次函数难度4的选择题1道、填空题1道",
    )

    result = service.send_message(conversation.id, "请解释勾股定理")

    assert result.content == "普通问答回复"
    assert len(provider.chat_requests) == 1
    assert [message.role for message in provider.chat_requests[0]] == [
        "system",
        "user",
    ]
    assert provider.chat_requests[0][-1].content == "请解释勾股定理"


def test_clearing_conversation_discards_in_memory_context_boundary(tmp_path) -> None:
    service, chat, provider, _registry = _service(tmp_path)
    conversation = chat.create_conversation()
    service.send_message(
        conversation.id,
        "请生成一次函数难度4的选择题1道、填空题1道",
    )
    service.send_message(conversation.id, "请解释勾股定理")
    chat.clear_conversation(conversation.id)
    provider.chat_responses = ["清空后的回复"]

    result = service.send_message(conversation.id, "重新开始普通问答")

    assert result.content == "清空后的回复"
    assert [message.role for message in provider.chat_requests[-1]] == [
        "system",
        "user",
    ]
