"""Replaceable language model providers."""

from edu_exam_agent.infrastructure.llm.provider import MockProvider, OpenAICompatibleProvider

__all__ = ["MockProvider", "OpenAICompatibleProvider"]
