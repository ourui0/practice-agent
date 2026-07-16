"""Minimal OpenAI-compatible JSON provider."""

from __future__ import annotations

import json
import urllib.request
from typing import Protocol


class LLMProvider(Protocol):
    def generate_json(self, system_prompt: str, user_prompt: str) -> dict: ...


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, model: str, api_key: str, timeout: int = 60) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        body = json.dumps(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.3,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
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
            payload = json.loads(response.read().decode("utf-8"))
        return json.loads(payload["choices"][0]["message"]["content"])


class MockProvider:
    def __init__(self, response: dict) -> None:
        self._response = response

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        return self._response
