"""Retrieval-grounded single-question generation workflow."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from edu_exam_agent.application.services.question_scoring import (
    QuestionScoreInput,
    calculate_question_score,
    evaluate_question,
)
from edu_exam_agent.domain.schemas import GeneratedQuestion
from edu_exam_agent.infrastructure.database.models import (
    QuestionFigureModel,
    QuestionModel,
    QuestionScoreDetailModel,
    QuestionSourceModel,
    QuestionValidationModel,
)
from edu_exam_agent.infrastructure.llm.provider import LLMProvider
from edu_exam_agent.infrastructure.rendering import render_diagram
from edu_exam_agent.infrastructure.retrieval import FtsRetriever, SearchResult


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    course_id: int
    knowledge_point: str
    question_type: str
    difficulty: int
    score: int = 5
    strict_material: bool = True
    document_id: int | None = None
    chapter_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class GenerationResult:
    question_id: int
    question: GeneratedQuestion
    quality_score: float
    recommendation_score: float
    boundary_passed: bool
    issues: tuple[str, ...]
    evidence: tuple[SearchResult, ...]
    figure_png: bytes | None = None


class QuestionGenerationAgent:
    FIGURE_REFERENCE = re.compile(
        r"(?:如|见|根据|观察)(?:下|上)?图(?:所示|中)?|(?:下|上)图(?:所示|中)?|示意图"
    )
    def __init__(
        self, engine: Engine, retriever: FtsRetriever, provider: LLMProvider, model_name: str
    ) -> None:
        self._engine = engine
        self._retriever = retriever
        self._provider = provider
        self._model_name = model_name

    def generate(self, request: GenerationRequest) -> GenerationResult:
        evidence = self._retriever.search(
            request.knowledge_point,
            request.course_id,
            document_id=request.document_id,
            chapter_ids=list(request.chapter_ids),
            limit=5,
        )
        if not evidence and (request.document_id is not None or request.chapter_ids):
            evidence = self._retriever.scope_context(
                request.course_id,
                document_id=request.document_id,
                chapter_ids=list(request.chapter_ids),
                limit=5,
            )
        if request.strict_material and not evidence:
            raise ValueError("严格教材模式下没有找到足够的教材依据")
        context = "\n\n".join(
            f"[{item.document_name} / {item.chapter_title} / 第{item.page_start}页]\n{item.excerpt}"
            for item in evidence
        )
        system_prompt = (
            "你是严谨的教师出题助手。只能依据给定教材，输出单个JSON对象，不得输出Markdown。"
            "字段必须包含question_type, stem, options, answer, analysis, scoring_criteria, "
            "knowledge_points, difficulty, estimated_time_minutes, score。"
            "options必须是对象数组，例如"
            '[{"label":"A","content":"选项内容"},{"label":"B","content":"选项内容"}]；'
            "非选择题的options必须是空数组。knowledge_points必须是字符串数组。"
            "若题目需要配图，必须额外返回diagram对象；否则diagram为null。diagram格式："
            '{"kind":"geometry或coordinate","points":[{"label":"A","x":0,"y":0}],'
            '"segments":[{"start":"A","end":"B","dashed":false}],'
            '"show_axes":false,"caption":""}。所有线段端点必须出现在points中。'
            "题干引用‘如图、图中、示意图’时diagram绝对不能为null。"
        )
        user_prompt = (
            f"知识点：{request.knowledge_point}\n题型：{request.question_type}\n"
            f"难度：{request.difficulty}\n分值：{request.score}\n教材依据：\n{context}"
        )
        question = None
        for _attempt in range(3):
            try:
                payload = self._provider.generate_json(system_prompt, user_prompt)
                payload = self._normalize_payload(payload, request)
                question = GeneratedQuestion.model_validate(payload)
            except ValidationError as exc:
                fields = ", ".join(
                    ".".join(str(part) for part in error["loc"])
                    for error in exc.errors()[:4]
                )
                raise ValueError(
                    f"模型返回的题目格式不完整（字段：{fields}），请重新生成；"
                    "若反复出现，请更换模型或检查模型是否支持 JSON 输出。"
                ) from exc
            if not self._references_missing_figure(question):
                break
            user_prompt += "\n上一次题目依赖未提供的图片。请重新生成完全不需要配图的题目。"
            question = None
        if question is None:
            raise ValueError("模型连续生成了依赖配图的题目，已拒绝保存；请重新生成")
        issues = self._quality_issues(question, request, bool(evidence))
        boundary_passed = bool(evidence) and request.knowledge_point in question.knowledge_points
        evaluation = evaluate_question(question, len(evidence), boundary_passed, issues)
        quality_score = evaluation.quality_score
        recommendation = calculate_question_score(
            QuestionScoreInput(quality_score, question.difficulty, request.difficulty)
        ).total
        figure_svg = None
        figure_png = None
        if question.diagram is not None:
            figure_svg, figure_png = render_diagram(question.diagram)
        question_id = self._save(
            request.course_id,
            question,
            evidence,
            issues,
            quality_score,
            recommendation,
            boundary_passed,
            figure_svg,
            figure_png,
            evaluation,
        )
        return GenerationResult(
            question_id,
            question,
            quality_score,
            recommendation,
            boundary_passed,
            tuple(issues),
            tuple(evidence),
            figure_png,
        )

    @staticmethod
    def _normalize_payload(payload: dict, request: GenerationRequest) -> dict:
        """Treat teacher-selected generation parameters as authoritative metadata."""
        if not isinstance(payload, dict):
            return payload
        normalized = dict(payload)
        normalized["question_type"] = request.question_type
        normalized["difficulty"] = request.difficulty
        normalized["score"] = request.score
        if not isinstance(normalized.get("estimated_time_minutes"), int):
            normalized["estimated_time_minutes"] = 3
        points = normalized.get("knowledge_points")
        if not isinstance(points, list):
            points = []
        normalized["knowledge_points"] = [
            request.knowledge_point,
            *(point for point in points if point != request.knowledge_point),
        ]
        return normalized

    @classmethod
    def _references_missing_figure(cls, question: GeneratedQuestion) -> bool:
        content = "\n".join(
            [question.stem, question.analysis, *(option.content for option in question.options)]
        )
        return bool(cls.FIGURE_REFERENCE.search(content)) and question.diagram is None

    @staticmethod
    def _quality_issues(
        question: GeneratedQuestion, request: GenerationRequest, has_evidence: bool
    ) -> list[str]:
        issues = []
        if question.question_type != request.question_type:
            issues.append("模型返回题型与要求不一致")
        if question.difficulty != request.difficulty:
            issues.append("模型返回难度与要求不一致")
        if question.score != request.score:
            issues.append("模型返回分值与要求不一致")
        if not has_evidence:
            issues.append("缺少教材依据")
        if request.knowledge_point not in question.knowledge_points:
            issues.append("知识点标签与要求不一致")
        return issues

    def _save(
        self,
        course_id: int,
        question: GeneratedQuestion,
        evidence: list[SearchResult],
        issues: list[str],
        quality: float,
        recommendation: float,
        boundary: bool,
        figure_svg: str | None,
        figure_png: bytes | None,
        evaluation,
    ) -> int:
        with Session(self._engine) as session, session.begin():
            row = QuestionModel(
                course_id=course_id,
                question_type=question.question_type,
                stem=question.stem,
                options_json=json.dumps(
                    [x.model_dump() for x in question.options], ensure_ascii=False
                ),
                answer=question.answer,
                analysis=question.analysis,
                scoring_criteria=question.scoring_criteria,
                knowledge_points_json=json.dumps(question.knowledge_points, ensure_ascii=False),
                difficulty=question.difficulty,
                estimated_time_minutes=question.estimated_time_minutes,
                score=question.score,
                quality_score=quality,
                recommendation_score=recommendation,
                boundary_passed=boundary,
                status="validated" if not issues else "needs_review",
                generation_model=self._model_name,
            )
            session.add(row)
            session.flush()
            for item in evidence:
                session.add(
                    QuestionSourceModel(
                        question_id=row.id, chunk_id=item.chunk_id, evidence=item.excerpt
                    )
                )
            if question.diagram is not None and figure_svg is not None and figure_png is not None:
                session.add(
                    QuestionFigureModel(
                        question_id=row.id,
                        spec_json=question.diagram.model_dump_json(),
                        svg_text=figure_svg,
                        png_data=figure_png,
                    )
                )
            session.add(
                QuestionValidationModel(
                    question_id=row.id,
                    passed=not issues and boundary,
                    quality_score=quality,
                    issues_json=json.dumps(issues, ensure_ascii=False),
                )
            )
            session.add(
                QuestionScoreDetailModel(
                    question_id=row.id,
                    total_points=evaluation.total_points,
                    dimensions_json=json.dumps(evaluation.dimensions, ensure_ascii=False),
                    calculation_load=evaluation.calculation_load,
                    fusion_count=evaluation.fusion_count,
                    reasoning_steps=evaluation.reasoning_steps,
                    hard_point_count=evaluation.hard_point_count,
                    estimated_difficulty=evaluation.estimated_difficulty,
                    notes_json=json.dumps(evaluation.notes, ensure_ascii=False),
                )
            )
            return row.id
