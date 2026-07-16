"""Replaceable document parser adapters."""

from edu_exam_agent.infrastructure.parsers.document_parser import (
    ParsedDocument,
    ParsedPage,
    ParserRegistry,
)

__all__ = ["ParsedDocument", "ParsedPage", "ParserRegistry"]
