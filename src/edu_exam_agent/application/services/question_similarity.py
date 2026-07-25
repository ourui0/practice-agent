"""Deterministic question fingerprints, mother-model tags and duplicate relations."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from edu_exam_agent.domain.schemas import GeneratedQuestion
from edu_exam_agent.infrastructure.database.models import (
    QuestionDuplicateRelationModel,
    QuestionFingerprintModel,
    QuestionModel,
)

DUPLICATE_THRESHOLD = 0.85
HIGH_SIMILARITY_THRESHOLD = 0.70
WARNING_THRESHOLD = 0.55


MODEL_TAG_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("折叠模型", (r"折叠|翻折|折痕|沿.+折",)),
    ("动点模型", (r"动点|运动时间|每秒|从.+出发",)),
    ("最短路径", (r"最短路径|距离之和|将军饮马|(?:线段|路程|周长).+最小",)),
    ("角平分线模型", (r"角平分线|平分∠|平分角",)),
    ("对角线中点模型", (r"对角线.+中点|对角线互相平分|交于.+中点",)),
    ("中点四边形", (r"分别是.+中点|中点四边形|依次为.+中点",)),
    ("旋转全等", (r"旋转|绕.+旋转|手拉手",)),
    ("一线三等角", (r"一线三等角|三个角相等",)),
    ("坐标几何", (r"平面直角坐标系|坐标为|坐标轴",)),
    ("参数分类", (r"参数|分类讨论|分情况|取值范围",)),
    ("存在性问题", (r"是否存在|存在.+使|不存在",)),
    ("面积最值", (r"面积.*最[大小]值?|面积的最值",)),
    ("方程建模", (r"建立方程|列方程|方程模型",)),
    ("函数交点", (r"函数.+交点|图像.+相交",)),
    ("勾股构造", (r"勾股定理|直角三角形.+求|作.+垂线",)),
    ("辅助线构造", (r"辅助线|延长.+交|连接.+|作.+平行线|作.+垂线",)),
    ("相似三角形", (r"相似三角形|△.+∽△|相似比",)),
    ("全等三角形", (r"全等三角形|△.+≌△",)),
    ("特殊四边形判定", (r"判定.+(?:平行四边形|矩形|菱形|正方形)",)),
    ("梯形综合", (r"梯形|上底|下底|中位线",)),
)

MATH_KEYWORDS = (
    "证明",
    "求证",
    "计算",
    "化简",
    "解方程",
    "分类讨论",
    "取值范围",
    "最大值",
    "最小值",
    "是否存在",
    "动点",
    "折叠",
    "旋转",
    "角平分线",
    "中点",
    "对角线",
    "垂直",
    "平行",
    "全等",
    "相似",
    "坐标",
    "面积",
    "周长",
    "方程",
    "函数",
)


@dataclass(frozen=True, slots=True)
class QuestionFingerprint:
    normalized_text: str
    text_hash: str
    math_signature: str
    model_tags: tuple[str, ...]
    question_type: str


@dataclass(frozen=True, slots=True)
class SimilarityBreakdown:
    total: float
    text: float
    math: float
    model: float
    level: str


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    question_id: int
    stem: str
    breakdown: SimilarityBreakdown
    shared_model_tags: tuple[str, ...]


def normalize_question_text(text: str) -> str:
    """Normalize superficial variations while preserving Chinese semantic structure."""
    value = unicodedata.normalize("NFKC", text).lower()
    value = re.sub(r"^\s*\d+[.、)]\s*", "", value)
    value = re.sub(r"\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?", "#", value)
    value = re.sub(r"[a-z]+", "v", value)
    value = re.sub(r"[（）()【】\[\]{}，,。.!！?？:：;；、\s]", "", value)
    return value


def extract_model_tags(stem: str, analysis: str = "") -> tuple[str, ...]:
    text = f"{stem}\n{analysis}"
    return tuple(
        tag
        for tag, patterns in MODEL_TAG_RULES
        if any(re.search(pattern, text) for pattern in patterns)
    )


def build_fingerprint(
    stem: str,
    analysis: str,
    knowledge_points: tuple[str, ...] | list[str],
    question_type: str,
) -> QuestionFingerprint:
    normalized = normalize_question_text(stem)
    math_tokens: list[str] = [f"type:{question_type}"]
    combined = f"{stem}\n{analysis}"
    math_tokens.extend(keyword for keyword in MATH_KEYWORDS if keyword in combined)
    for symbol in ("=", "≠", "≥", "≤", ">", "<", "⊥", "∥", "√", "+", "-", "×", "÷", "∠", "△"):
        count = combined.count(symbol)
        if count:
            math_tokens.append(f"{symbol}:{min(count, 6)}")
    math_tokens.extend(f"kp:{normalize_question_text(point)}" for point in knowledge_points)
    formulas = re.findall(r"[A-Za-z0-9√²³()+\-×÷=<>≤≥]{3,}", combined)
    math_tokens.extend(
        f"formula:{normalize_question_text(formula)}" for formula in formulas[:12]
    )
    signature = json.dumps(sorted(math_tokens), ensure_ascii=False, separators=(",", ":"))
    return QuestionFingerprint(
        normalized_text=normalized,
        text_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        math_signature=signature,
        model_tags=extract_model_tags(stem, analysis),
        question_type=question_type,
    )


def fingerprint_generated(question: GeneratedQuestion) -> QuestionFingerprint:
    return build_fingerprint(
        question.stem,
        question.analysis,
        question.knowledge_points,
        question.question_type,
    )


def fingerprint_model(question: QuestionModel) -> QuestionFingerprint:
    try:
        points = json.loads(question.knowledge_points_json)
    except (TypeError, json.JSONDecodeError):
        points = []
    return build_fingerprint(
        question.stem,
        question.analysis,
        points if isinstance(points, list) else [],
        question.question_type,
    )


def compare_fingerprints(
    first: QuestionFingerprint, second: QuestionFingerprint
) -> SimilarityBreakdown:
    if first.text_hash == second.text_hash:
        return SimilarityBreakdown(1.0, 1.0, 1.0, 1.0, "duplicate")
    text_sequence = SequenceMatcher(
        None, first.normalized_text, second.normalized_text, autojunk=False
    ).ratio()
    text_ngrams = _jaccard(_ngrams(first.normalized_text), _ngrams(second.normalized_text))
    text_score = (text_sequence + text_ngrams) / 2
    math_score = _counter_jaccard(
        Counter(json.loads(first.math_signature)),
        Counter(json.loads(second.math_signature)),
    )
    model_score = _jaccard(set(first.model_tags), set(second.model_tags))
    same_type_bonus = 0.04 if first.question_type == second.question_type else 0.0
    total = min(
        1.0,
        text_score * 0.45 + math_score * 0.30 + model_score * 0.21 + same_type_bonus,
    )
    if text_score >= 0.94:
        total = max(total, 0.88)
    level = similarity_level(total)
    return SimilarityBreakdown(
        round(total, 4),
        round(text_score, 4),
        round(math_score, 4),
        round(model_score, 4),
        level,
    )


def similarity_level(score: float) -> str:
    if score >= DUPLICATE_THRESHOLD:
        return "duplicate"
    if score >= HIGH_SIMILARITY_THRESHOLD:
        return "high"
    if score >= WARNING_THRESHOLD:
        return "warning"
    return "none"


class QuestionSimilarityService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def analyze_candidate(
        self,
        course_id: int,
        question: GeneratedQuestion,
        *,
        exclude_question_id: int | None = None,
        limit: int = 3,
    ) -> tuple[DuplicateMatch, ...]:
        candidate = fingerprint_generated(question)
        with Session(self._engine) as session:
            statement = select(QuestionModel).where(QuestionModel.course_id == course_id)
            if exclude_question_id is not None:
                statement = statement.where(QuestionModel.id != exclude_question_id)
            questions = list(session.scalars(statement))
        matches = []
        for existing in questions:
            existing_fingerprint = fingerprint_model(existing)
            breakdown = compare_fingerprints(candidate, existing_fingerprint)
            shared = tuple(
                tag for tag in candidate.model_tags if tag in existing_fingerprint.model_tags
            )
            matches.append(DuplicateMatch(existing.id, existing.stem, breakdown, shared))
        matches.sort(key=lambda item: (-item.breakdown.total, item.question_id))
        return tuple(matches[:limit])

    def closest_for_question(
        self, question_id: int, limit: int = 3
    ) -> tuple[DuplicateMatch, ...]:
        with Session(self._engine) as session:
            question = session.get(QuestionModel, question_id)
            if question is None:
                return ()
            generated = GeneratedQuestion.model_validate(
                {
                    "question_type": question.question_type,
                    "stem": question.stem,
                    "options": json.loads(question.options_json or "[]"),
                    "answer": question.answer,
                    "analysis": question.analysis,
                    "scoring_criteria": question.scoring_criteria,
                    "knowledge_points": json.loads(question.knowledge_points_json or "[]"),
                    "difficulty": question.difficulty,
                    "estimated_time_minutes": question.estimated_time_minutes,
                    "score": question.score,
                }
            )
            course_id = question.course_id
        return self.analyze_candidate(
            course_id, generated, exclude_question_id=question_id, limit=limit
        )

    def persist_metadata(
        self,
        question_id: int,
        requested_difficulty: int,
        calibrated_difficulty: int,
        difficulty_features: tuple[str, ...],
        difficulty_reasons: tuple[str, ...],
        matches: tuple[DuplicateMatch, ...] = (),
    ) -> None:
        with Session(self._engine) as session, session.begin():
            question = session.get(QuestionModel, question_id)
            if question is None:
                raise ValueError("题目不存在")
            fingerprint = fingerprint_model(question)
            row = session.scalar(
                select(QuestionFingerprintModel).where(
                    QuestionFingerprintModel.question_id == question_id
                )
            )
            values = {
                "normalized_text": fingerprint.normalized_text,
                "text_hash": fingerprint.text_hash,
                "math_signature": fingerprint.math_signature,
                "model_tags_json": json.dumps(fingerprint.model_tags, ensure_ascii=False),
                "requested_difficulty": requested_difficulty,
                "calibrated_difficulty": calibrated_difficulty,
                "difficulty_features_json": json.dumps(
                    difficulty_features, ensure_ascii=False
                ),
                "difficulty_reasons_json": json.dumps(difficulty_reasons, ensure_ascii=False),
            }
            if row is None:
                session.add(QuestionFingerprintModel(question_id=question_id, **values))
            else:
                for name, value in values.items():
                    setattr(row, name, value)
            session.execute(
                delete(QuestionDuplicateRelationModel).where(
                    QuestionDuplicateRelationModel.question_id == question_id
                )
            )
            for match in matches:
                if match.breakdown.level == "none":
                    continue
                session.add(
                    QuestionDuplicateRelationModel(
                        question_id=question_id,
                        matched_question_id=match.question_id,
                        total_similarity=match.breakdown.total,
                        text_similarity=match.breakdown.text,
                        math_similarity=match.breakdown.math,
                        model_similarity=match.breakdown.model,
                        level=match.breakdown.level,
                        reviewer="local",
                    )
                )

    def avoidance_context(self, course_id: int, limit: int = 20) -> str:
        with Session(self._engine) as session:
            questions = list(
                session.scalars(
                    select(QuestionModel)
                    .where(QuestionModel.course_id == course_id)
                    .order_by(QuestionModel.id.desc())
                    .limit(limit)
                )
            )
        if not questions:
            return ""
        tags: list[str] = []
        summaries: list[str] = []
        for question in questions:
            fingerprint = fingerprint_model(question)
            tags.extend(fingerprint.model_tags)
            summaries.append(question.stem.replace("\n", " ")[:80])
        tag_text = "、".join(dict.fromkeys(tags)) or "暂无明确母题标签"
        return (
            f"近期已用母题：{tag_text}\n"
            "以下近期题目不得只替换数字、字母或背景后再次生成：\n- "
            + "\n- ".join(summaries[:10])
        )

    def backfill(self, course_id: int | None = None) -> tuple[int, int]:
        with Session(self._engine) as session:
            statement = select(QuestionModel).order_by(QuestionModel.id)
            if course_id is not None:
                statement = statement.where(QuestionModel.course_id == course_id)
            questions = list(session.scalars(statement))
        relation_count = 0
        for question in questions:
            matches = self.refresh_question(question.id, question.difficulty, limit=10)
            relation_count += sum(
                match.breakdown.level != "none" for match in matches
            )
        return len(questions), relation_count

    def refresh_question(
        self,
        question_id: int,
        requested_difficulty: int | None = None,
        *,
        limit: int = 3,
    ) -> tuple[DuplicateMatch, ...]:
        with Session(self._engine) as session:
            question = session.get(QuestionModel, question_id)
            if question is None:
                raise ValueError("题目不存在")
            requested = requested_difficulty or question.difficulty
        matches = self.closest_for_question(question_id, limit=limit)
        detail = self._score_detail(question_id)
        self.persist_metadata(
            question_id,
            requested,
            detail[0],
            detail[1],
            detail[2],
            matches,
        )
        return matches

    def _score_detail(self, question_id: int) -> tuple[int, tuple[str, ...], tuple[str, ...]]:
        from edu_exam_agent.application.services.question_scoring import (
            calibrate_question_difficulty,
            evaluate_question,
        )

        with Session(self._engine) as session:
            question = session.get(QuestionModel, question_id)
            if question is None:
                raise ValueError("题目不存在")
            generated = GeneratedQuestion.model_validate(
                {
                    "question_type": question.question_type,
                    "stem": question.stem,
                    "options": json.loads(question.options_json or "[]"),
                    "answer": question.answer,
                    "analysis": question.analysis,
                    "scoring_criteria": question.scoring_criteria,
                    "knowledge_points": json.loads(question.knowledge_points_json or "[]"),
                    "difficulty": question.difficulty,
                    "estimated_time_minutes": question.estimated_time_minutes,
                    "score": question.score,
                }
            )
        evaluation = evaluate_question(generated, 1, question.boundary_passed)
        calibration = calibrate_question_difficulty(generated, evaluation)
        return calibration.level, calibration.features, calibration.reasons


def _ngrams(value: str, size: int = 2) -> set[str]:
    if len(value) < size:
        return {value} if value else set()
    return {value[index : index + size] for index in range(len(value) - size + 1)}


def _jaccard(first: set[str], second: set[str]) -> float:
    if not first and not second:
        return 0.0
    return len(first & second) / len(first | second)


def _counter_jaccard(first: Counter, second: Counter) -> float:
    keys = set(first) | set(second)
    if not keys:
        return 0.0
    intersection = sum(min(first[key], second[key]) for key in keys)
    union = sum(max(first[key], second[key]) for key in keys)
    return intersection / union if union else 0.0
