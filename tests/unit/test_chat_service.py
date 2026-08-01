from __future__ import annotations

import urllib.error

import pytest

from edu_exam_agent.application.services.chat_service import (
    SYSTEM_PROMPT,
    ChatCancelledError,
    ChatService,
    ChatServiceError,
)
from edu_exam_agent.application.services.provider_service import ProviderConfig
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)


class RecordingProvider:
    def __init__(self, replies: list[str] | None = None, error: Exception | None = None):
        self.replies = replies or ["回答"]
        self.error = error
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


class FakeProviderService:
    def __init__(self, provider: RecordingProvider):
        self.provider = provider

    def get_default(self):
        return ProviderConfig("测试服务", "https://example.test", "test-model", True)

    def create_provider(self):
        return self.provider, "test-model"


def _service(tmp_path, provider=None, max_history_characters=24_000):
    engine = create_database_engine(tmp_path / "chat.db")
    initialize_database(engine)
    recording = provider or RecordingProvider()
    return (
        ChatService(
            engine,
            FakeProviderService(recording),
            max_history_characters=max_history_characters,
        ),
        recording,
    )


def test_multi_turn_chat_is_saved_in_order_and_system_prompt_is_once(tmp_path) -> None:
    service, provider = _service(
        tmp_path, RecordingProvider(["第一次回答", "第二次回答"])
    )
    conversation = service.create_conversation()

    service.send_message(conversation.id, "第一个问题")
    service.send_message(conversation.id, "第二个问题")

    rows = service.get_messages(conversation.id)
    assert [(row.role, row.content) for row in rows] == [
        ("user", "第一个问题"),
        ("assistant", "第一次回答"),
        ("user", "第二个问题"),
        ("assistant", "第二次回答"),
    ]
    assert [message.role for message in provider.calls[1]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert sum(message.content == SYSTEM_PROMPT for message in provider.calls[1]) == 1
    assert service.list_conversations()[0].title == "第一个问题"


def test_failure_keeps_user_message_without_fake_assistant(tmp_path) -> None:
    service, _provider = _service(
        tmp_path,
        RecordingProvider(error=urllib.error.URLError("offline")),
    )
    conversation = service.create_conversation()

    with pytest.raises(ChatServiceError, match="无法连接"):
        service.send_message(conversation.id, "请保留这个问题")

    rows = service.get_messages(conversation.id)
    assert [(row.role, row.content) for row in rows] == [
        ("user", "请保留这个问题")
    ]


def test_cancel_keeps_user_and_never_saves_assistant(tmp_path) -> None:
    service, provider = _service(tmp_path)
    conversation = service.create_conversation()

    with pytest.raises(ChatCancelledError):
        service.send_message(conversation.id, "停止也要保留", lambda: True)

    assert provider.calls == []
    rows = service.get_messages(conversation.id)
    assert [(row.role, row.content) for row in rows] == [
        ("user", "停止也要保留")
    ]


def test_late_response_after_cancel_is_not_saved(tmp_path) -> None:
    cancelled = {"value": False}

    class CancellingProvider(RecordingProvider):
        def chat(self, messages):
            self.calls.append(messages)
            cancelled["value"] = True
            return "这是一条迟到的回复"

    service, _provider = _service(tmp_path, CancellingProvider())
    conversation = service.create_conversation()

    with pytest.raises(ChatCancelledError):
        service.send_message(
            conversation.id,
            "用户已经点击停止",
            lambda: cancelled["value"],
        )

    rows = service.get_messages(conversation.id)
    assert [row.role for row in rows] == ["user"]


def test_history_is_truncated_from_the_oldest_messages(tmp_path) -> None:
    service, provider = _service(
        tmp_path,
        RecordingProvider(["甲" * 650, "第二次"]),
        max_history_characters=1_000,
    )
    conversation = service.create_conversation()
    service.send_message(conversation.id, "旧" * 650)
    service.send_message(conversation.id, "新" * 650)

    request = provider.calls[1]
    assert request[0].role == "system"
    assert request[-1].content == "新" * 650
    assert all(message.content != "旧" * 650 for message in request)


def test_regeneration_replaces_last_reply_but_cancel_preserves_it(tmp_path) -> None:
    service, provider = _service(
        tmp_path, RecordingProvider(["原回答", "新回答"])
    )
    conversation = service.create_conversation()
    service.send_message(conversation.id, "问题")

    with pytest.raises(ChatCancelledError):
        service.regenerate_last_response(conversation.id, lambda: True)
    assert service.get_messages(conversation.id)[-1].content == "原回答"

    service.regenerate_last_response(conversation.id)
    rows = service.get_messages(conversation.id)
    assert [(row.role, row.content) for row in rows] == [
        ("user", "问题"),
        ("assistant", "新回答"),
    ]
    assert len(provider.calls) == 2


def test_clear_delete_and_title_limit(tmp_path) -> None:
    service, _provider = _service(tmp_path)
    conversation = service.create_conversation()
    service.send_message(conversation.id, "这是一条很长的问题" * 10)
    assert len(service.list_conversations()[0].title.rstrip("…")) <= 30

    service.clear_conversation(conversation.id)
    assert service.get_messages(conversation.id) == []
    assert service.list_conversations()[0].title == "新对话"

    service.delete_conversation(conversation.id)
    assert service.list_conversations() == []


def test_reset_history_starts_clean_ordinary_context(tmp_path) -> None:
    service, provider = _service(
        tmp_path,
        RecordingProvider(["旧任务回复", "新话题回复", "新话题追问回复"]),
    )
    conversation = service.create_conversation()
    service.send_message(conversation.id, "旧任务内容")

    switched = service.send_message(
        conversation.id,
        "这是一个新话题",
        reset_history=True,
    )
    service.send_message(
        conversation.id,
        "继续刚才的新话题",
        history_start_message_id=switched.request_message_id,
    )

    assert [message.role for message in provider.calls[1]] == ["system", "user"]
    assert provider.calls[1][-1].content == "这是一个新话题"
    assert [message.role for message in provider.calls[2]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert all(message.content != "旧任务内容" for message in provider.calls[2])


def test_generic_deflection_is_retried_with_clean_prompt(tmp_path) -> None:
    service, provider = _service(
        tmp_path,
        RecordingProvider(
            [
                "有什么想聊的吗？需要我帮什么都可以，尽管说，我随时可以。",
                "勾股定理说明直角三角形两直角边平方和等于斜边平方。",
            ]
        ),
    )
    conversation = service.create_conversation()

    response = service.send_message(conversation.id, "请解释勾股定理")

    assert len(provider.calls) == 2
    assert response.content.startswith("勾股定理")
    assert [message.role for message in provider.calls[1]] == [
        "system",
        "system",
        "user",
    ]
