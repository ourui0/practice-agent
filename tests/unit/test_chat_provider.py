from __future__ import annotations

import json

from edu_exam_agent.infrastructure.llm.provider import (
    AssistantToolResponse,
    ChatMessage,
    OpenAICompatibleProvider,
    ToolDefinition,
)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": "普通文本回复"}}]}
        ).encode()


def test_chat_request_does_not_enable_json_response_format(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        captured["authorization"] = request.headers["Authorization"]
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        "https://example.test",
        "chat-model",
        "secret-token",
        timeout=12,
    )

    result = provider.chat(
        [
            ChatMessage("system", "系统"),
            ChatMessage("user", "问题"),
        ]
    )

    assert result == "普通文本回复"
    assert "response_format" not in captured["body"]
    assert captured["body"]["stream"] is False
    assert [item["role"] for item in captured["body"]["messages"]] == [
        "system",
        "user",
    ]
    assert captured["timeout"] == 12
    assert captured["authorization"] == "Bearer secret-token"


def test_structured_generation_still_requests_json(monkeypatch) -> None:
    captured = {}

    class JsonResponse(_Response):
        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": '{"value": 1}'}}]}
            ).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode())
        return JsonResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        "https://example.test", "json-model", "secret-token"
    )

    assert provider.generate_json("system", "user") == {"value": 1}
    assert captured["body"]["response_format"] == {"type": "json_object"}


def test_tool_chat_sends_definitions_and_parses_multiple_calls(monkeypatch) -> None:
    captured = {}

    class ToolResponse(_Response):
        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "list_courses",
                                            "arguments": "{}",
                                        },
                                    },
                                    {
                                        "id": "call_2",
                                        "type": "function",
                                        "function": {
                                            "name": "list_textbooks",
                                            "arguments": '{"course_id": 3}',
                                        },
                                    },
                                ],
                            }
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode())
        return ToolResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        "https://example.test", "tool-model", "secret-token"
    )
    response = provider.chat_with_tools(
        [ChatMessage("user", "查询课程")],
        [
            ToolDefinition(
                "list_courses",
                "查询课程",
                {"type": "object", "properties": {}, "additionalProperties": False},
            )
        ],
    )

    assert isinstance(response, AssistantToolResponse)
    assert [call.name for call in response.tool_calls] == [
        "list_courses",
        "list_textbooks",
    ]
    assert response.tool_calls[1].arguments == {"course_id": 3}
    assert captured["body"]["tool_choice"] == "auto"
    assert "response_format" not in captured["body"]
    assert captured["body"]["tools"][0]["function"]["name"] == "list_courses"
