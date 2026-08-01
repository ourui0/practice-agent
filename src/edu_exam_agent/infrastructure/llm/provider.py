"""OpenAI-compatible provider for structured generation and normal chat."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str = ""
    tool_call_id: str = ""
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class AssistantToolResponse:
    content: str
    tool_calls: tuple[ToolCall, ...]


class LLMProvider(Protocol):
    def generate_json(self, system_prompt: str, user_prompt: str) -> dict: ...

    def chat(self, messages: list[ChatMessage]) -> str: ...

    def chat_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> AssistantToolResponse: ...


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, model: str, api_key: str, timeout: int = 60) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        payload = self._post(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.3,
                "stream": False,
            }
        )
        return json.loads(self._message_content(payload))

    def chat(self, messages: list[ChatMessage]) -> str:
        """Return ordinary text without enabling JSON response mode."""
        payload = self._post(
            {
                "model": self._model,
                "messages": [self._serialize_message(message) for message in messages],
                "temperature": 0.3,
                "stream": False,
            }
        )
        content = self._message_content(payload).strip()
        if not content:
            raise ValueError("模型返回了空内容")
        return content

    def chat_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> AssistantToolResponse:
        """Request a normal assistant response with a strict function whitelist."""
        payload = self._post(
            {
                "model": self._model,
                "messages": [self._serialize_message(message) for message in messages],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.parameters,
                        },
                    }
                    for tool in tools
                ],
                "tool_choice": "auto",
                "temperature": 0.3,
                "stream": False,
            }
        )
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("模型工具响应格式无效") from exc
        raw_calls = message.get("tool_calls") or []
        calls: list[ToolCall] = []
        for raw_call in raw_calls:
            try:
                function = raw_call["function"]
                arguments = json.loads(function.get("arguments") or "{}")
                if not isinstance(arguments, dict):
                    raise TypeError
                calls.append(
                    ToolCall(
                        id=str(raw_call["id"]),
                        name=str(function["name"]),
                        arguments=arguments,
                    )
                )
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("模型返回了无效的工具参数") from exc
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ValueError("模型工具响应内容无效")
        if not content.strip() and not calls:
            raise ValueError("模型没有返回文字或工具调用")
        return AssistantToolResponse(content.strip(), tuple(calls))

    @staticmethod
    def _serialize_message(message: ChatMessage) -> dict:
        payload: dict[str, object] = {
            "role": message.role,
            "content": message.content,
        }
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        return payload

    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _message_content(payload: dict) -> str:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("模型响应格式无效") from exc
        if not isinstance(content, str):
            raise ValueError("模型响应内容无效")
        return content


class MockProvider:
    def __init__(
        self,
        response: dict,
        chat_response: str = "模拟回复",
        tool_responses: list[AssistantToolResponse] | None = None,
    ) -> None:
        self._response = response
        self._chat_response = chat_response
        self._tool_responses = list(tool_responses or [])
        self.tool_calls: list[tuple[list[ChatMessage], list[ToolDefinition]]] = []

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        return self._response

    def chat(self, messages: list[ChatMessage]) -> str:
        return self._chat_response

    def chat_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> AssistantToolResponse:
        self.tool_calls.append((messages, tools))
        if self._tool_responses:
            return self._tool_responses.pop(0)
        return AssistantToolResponse(self._chat_response, ())
