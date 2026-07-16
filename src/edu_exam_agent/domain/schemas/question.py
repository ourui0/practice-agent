"""Structured question output accepted from model providers."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=5)
    content: str = Field(min_length=1)


class DiagramPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=8)
    x: float = Field(ge=-1000, le=1000)
    y: float = Field(ge=-1000, le=1000)


class DiagramSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str
    end: str
    dashed: bool = False


class QuestionDiagram(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(default="geometry", pattern="^(geometry|coordinate)$")
    points: list[DiagramPoint] = Field(min_length=2, max_length=30)
    segments: list[DiagramSegment] = Field(default_factory=list, max_length=60)
    show_axes: bool = False
    caption: str = Field(default="", max_length=100)


class GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_type: str
    stem: str = Field(min_length=5)
    options: list[QuestionOption] = Field(default_factory=list)
    answer: str = Field(min_length=1)
    analysis: str = Field(min_length=5)
    scoring_criteria: str = ""
    knowledge_points: list[str] = Field(min_length=1)
    difficulty: int = Field(ge=1, le=5)
    estimated_time_minutes: int = Field(default=3, ge=1, le=180)
    score: int = Field(default=5, ge=1, le=100)
    diagram: QuestionDiagram | None = None

    @field_validator("options", mode="before")
    @classmethod
    def normalize_options(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("选项必须是列表")
        normalized = []
        for index, option in enumerate(value):
            if isinstance(option, str):
                text = option.strip()
                match = re.match(r"^([A-Za-z])\s*[\.．、:：\)）-]\s*(.+)$", text)
                if match:
                    normalized.append(
                        {"label": match.group(1).upper(), "content": match.group(2).strip()}
                    )
                else:
                    normalized.append({"label": chr(65 + index), "content": text})
            else:
                normalized.append(option)
        return normalized

    @model_validator(mode="after")
    def validate_choice_options(self):
        if self.question_type in {"单项选择题", "多项选择题", "选择题"} and len(self.options) < 4:
            raise ValueError("选择题至少需要四个选项")
        return self
