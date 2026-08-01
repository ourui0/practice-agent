"""Strict schemas shared by the teaching-agent tool registry."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edu_exam_agent.application.services.question_types import QUESTION_TYPE_ORDER

QUESTION_TYPE_ALIASES = {
    "选择题": "单项选择题",
    "单选题": "单项选择题",
    "单项选择题": "单项选择题",
    "填空题": "填空题",
    "计算题": "计算题",
    "应用题": "应用题",
}


class StrictToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyArgs(StrictToolArgs):
    pass


class CourseArgs(StrictToolArgs):
    course_id: int = Field(gt=0)


class TextbookArgs(CourseArgs):
    document_id: int = Field(gt=0)


class KnowledgePointArgs(CourseArgs):
    chapter_ids: list[int] = Field(default_factory=list, max_length=100)


class InventoryArgs(CourseArgs):
    chapter_ids: list[int] = Field(default_factory=list, max_length=100)
    knowledge_point_ids: list[int] = Field(default_factory=list, max_length=100)
    difficulty: int = Field(default=3, ge=1, le=5)
    question_type_counts: dict[str, int]
    document_id: int | None = Field(default=None, gt=0)
    exclude_recent: bool = True

    @field_validator("question_type_counts")
    @classmethod
    def validate_counts(cls, value: dict[str, int]) -> dict[str, int]:
        return normalize_question_type_counts(value)


class GenerationPlanArgs(CourseArgs):
    document_id: int | None = Field(default=None, gt=0)
    chapter_ids: list[int] = Field(default_factory=list, max_length=100)
    chapter_query: str = Field(default="", max_length=100)
    knowledge_point_ids: list[int] = Field(default_factory=list, max_length=100)
    difficulty: int = Field(default=3, ge=1, le=5)
    question_type_counts: dict[str, int]
    total_count: int | None = Field(default=None, ge=1, le=100)
    title: str = Field(default="AI生成训练", min_length=1, max_length=200)
    exclude_recent: bool = True
    allow_ai_backfill: bool = True
    include_answers: bool = True
    estimated_duration_minutes: int = Field(default=60, ge=1, le=600)
    assemble_paper: bool = True
    export_word: bool = False

    @field_validator("question_type_counts")
    @classmethod
    def validate_counts(cls, value: dict[str, int]) -> dict[str, int]:
        return normalize_question_type_counts(value)

    @model_validator(mode="after")
    def validate_total(self):
        calculated = sum(self.question_type_counts.values())
        if self.total_count is not None and self.total_count != calculated:
            raise ValueError("各题型数量之和与题目总数不一致")
        self.total_count = calculated
        return self


class PreparedGenerationPlan(GenerationPlanArgs):
    course_name: str
    document_name: str = ""
    chapter_names: list[str] = Field(default_factory=list)
    knowledge_points: list[str] = Field(default_factory=list)


class GenerateBatchArgs(StrictToolArgs):
    operation_id: str = Field(min_length=8, max_length=100)
    task_id: str = Field(min_length=8, max_length=100)
    plan: PreparedGenerationPlan


class GenerateSingleArgs(StrictToolArgs):
    operation_id: str = Field(min_length=8, max_length=100)
    task_id: str = Field(min_length=8, max_length=100)
    plan: PreparedGenerationPlan


class ProgressArgs(StrictToolArgs):
    task_id: str = Field(min_length=8, max_length=100)


class CancelTaskArgs(ProgressArgs):
    operation_id: str = Field(min_length=8, max_length=100)


class AssemblePaperArgs(StrictToolArgs):
    operation_id: str = Field(min_length=8, max_length=100)
    plan: PreparedGenerationPlan


class ExportPaperArgs(StrictToolArgs):
    operation_id: str = Field(min_length=8, max_length=100)
    paper_id: int = Field(gt=0)
    filename: str = Field(default="", max_length=180)


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_call_id: str
    name: str
    succeeded: bool
    content: dict
    user_message: str = ""
    private_content: dict = field(default_factory=dict)


def normalize_question_type_counts(value: dict[str, int]) -> dict[str, int]:
    if not value:
        raise ValueError("请至少设置一种题型数量")
    normalized = {question_type: 0 for question_type in QUESTION_TYPE_ORDER}
    for label, count in value.items():
        question_type = QUESTION_TYPE_ALIASES.get(label)
        if question_type is None:
            raise ValueError(f"不支持的题型：{label}")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("题型数量必须是非负整数")
        normalized[question_type] += count
    result = {
        question_type: normalized[question_type]
        for question_type in QUESTION_TYPE_ORDER
        if normalized[question_type] > 0
    }
    if not result:
        raise ValueError("题目总数必须大于0")
    return result
