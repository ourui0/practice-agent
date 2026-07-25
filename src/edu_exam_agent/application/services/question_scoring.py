"""Deterministic scoring and ranking rules for generated questions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from edu_exam_agent.domain.schemas import GeneratedQuestion


@dataclass(frozen=True, slots=True)
class QuestionScoreInput:
    """Normalized inputs used to calculate a question's recommendation score."""

    quality_score: float
    difficulty: int
    target_difficulty: int


@dataclass(frozen=True, slots=True)
class QuestionScore:
    """Explainable score returned to the UI and audit trail."""

    total: float
    quality_component: float
    difficulty_component: float


@dataclass(frozen=True, slots=True)
class QuestionEvaluation:
    quality_score: float
    total_points: float
    dimensions: dict[str, float]
    calculation_load: int
    fusion_count: int
    reasoning_steps: int
    hard_point_count: int
    estimated_difficulty: int
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DifficultyCalibration:
    """Rule-based five-level calibration independent from model self-reporting."""

    level: int
    requested_level: int
    meets_requested: bool
    features: tuple[str, ...]
    reasons: tuple[str, ...]
    direct_formula: bool


TOPIC_GROUPS = {
    "代数": ("方程", "不等式", "整式", "分式", "因式", "代数式"),
    "函数": ("函数", "坐标", "图像", "变量"),
    "几何": ("三角形", "平行", "相交", "角", "线段", "对称", "平移"),
    "统计": ("统计", "概率", "频数", "平均数", "中位数"),
}
HARD_MARKERS = (
    "分类讨论",
    "动点",
    "参数",
    "最值",
    "存在性",
    "辅助线",
    "综合",
    "证明",
    "反证",
    "归纳",
    "构造",
)
REASON_MARKERS = ("因为", "所以", "由", "可得", "进而", "因此", "分情况", "首先", "再")

HIGH_ORDER_FEATURES: tuple[tuple[str, str], ...] = (
    ("辅助线或图形转化", r"辅助线|作.+(?:垂线|平行线)|延长.+交|连接.+|折叠|旋转|对称"),
    ("参数或字母系数", r"参数|字母系数|关于[a-zA-Z]|含[a-zA-Z]的"),
    ("动点过程", r"动点|运动时间|每秒|从.+出发"),
    ("最值问题", r"最[大小]值|最短|最小|最大"),
    ("存在性讨论", r"是否存在|存在.+使|不存在"),
    ("分类或范围筛选", r"分类讨论|分情况|取值范围|舍去|不符合|检验"),
    ("证明或反证", r"证明|求证|反证"),
    ("方程建模", r"建立方程|列方程|设.+为|方程模型"),
)
TURNING_POINT_MARKERS = (
    "关键",
    "转化",
    "构造",
    "作辅助线",
    "分类讨论",
    "分情况",
    "取值范围",
    "舍去",
    "反证",
    "对称",
    "设",
)


def evaluate_question(
    question: GeneratedQuestion,
    evidence_count: int,
    boundary_passed: bool,
    issues: list[str] | tuple[str, ...] = (),
) -> QuestionEvaluation:
    """Return a deterministic, explainable 100-point quality evaluation."""
    text = "\n".join((question.stem, question.analysis, question.scoring_criteria))
    calculation_load = min(
        10,
        len(re.findall(r"\d+(?:\.\d+)?", text))
        + len(re.findall(r"[+\-×÷=*/^]|\\frac|√", text))
        + 2 * len(re.findall(r"解得|计算|化简|代入", text)),
    )
    topics = {
        group for group, words in TOPIC_GROUPS.items() if any(word in text for word in words)
    }
    fusion_count = max(len(set(question.knowledge_points)), len(topics), 1)
    reasoning_steps = min(6, sum(text.count(marker) for marker in REASON_MARKERS))
    hard_point_count = sum(marker in text for marker in HARD_MARKERS)

    structure = 7.0
    structure += 2 if question.answer.strip() else 0
    structure += 2 if question.scoring_criteria.strip() else 0
    structure += 1 if question.estimated_time_minutes > 0 else 0
    if question.question_type in {"单项选择题", "多项选择题", "选择题"}:
        structure += 2 if len(question.options) >= 4 else 0
    else:
        structure += 2 if not question.options else 0

    stem_length = len(question.stem.strip())
    clarity = 6 + min(stem_length / 35, 1) * 5
    if any(word in question.stem for word in ("适当", "相关", "某些", "等等")):
        clarity -= 2
    clarity = max(0, min(12, clarity))

    analysis_length = len(question.analysis.strip())
    analysis = 4 + min(analysis_length / 90, 1) * 6 + min(reasoning_steps, 3)
    analysis = min(14, analysis)
    grounding = min(14, (8 if boundary_passed else 0) + min(evidence_count, 3) * 2)

    if question.question_type in {"计算题", "应用题"}:
        calculation = 3 + calculation_load * 0.7
    else:
        calculation = 6 + min(calculation_load, 4) * 0.5
    calculation = min(10, calculation)

    fusion = min(12, 3 + fusion_count * 3)
    cognitive = min(12, 3 + reasoning_steps * 1.2 + hard_point_count * 2)
    difficulty_value = min(
        8,
        2 + calculation_load * 0.25 + (fusion_count - 1) * 1.5 + hard_point_count,
    )
    teaching_value = 4.0
    teaching_value += 2 if question.analysis.strip() != question.answer.strip() else 0
    teaching_value += 2 if question.scoring_criteria.strip() else 0
    teaching_value = min(8, teaching_value)

    dimensions = {
        "结构完整": round(structure, 2),
        "表达清晰": round(clarity, 2),
        "答案解析": round(analysis, 2),
        "教材依据": round(grounding, 2),
        "计算负荷": round(calculation, 2),
        "知识融合": round(fusion, 2),
        "思维深度": round(cognitive, 2),
        "难点价值": round(difficulty_value, 2),
        "教学价值": round(teaching_value, 2),
    }
    raw = sum(dimensions.values())
    penalty = len(issues) * 8
    total = max(0.0, min(100.0, raw - penalty))
    estimated_difficulty = min(
        5,
        max(
            1,
            round(
                1
                + calculation_load / 5
                + (fusion_count - 1) * 0.7
                + hard_point_count * 0.5
                + reasoning_steps / 6
            ),
        ),
    )
    notes = [
        f"计算负荷 {calculation_load}/10",
        f"融合知识点 {fusion_count} 个",
        f"推理层次 {reasoning_steps}",
        f"难点特征 {hard_point_count} 个",
    ]
    if issues:
        notes.append(f"质量问题扣分 {penalty} 分")
    return QuestionEvaluation(
        round(total / 100, 4),
        round(total, 2),
        dimensions,
        calculation_load,
        fusion_count,
        reasoning_steps,
        hard_point_count,
        estimated_difficulty,
        tuple(notes),
    )


def calculate_question_score(value: QuestionScoreInput) -> QuestionScore:
    """Combine quality (70%) and difficulty fit (30%) into a 100-point score."""
    if not 0 <= value.quality_score <= 1:
        raise ValueError("题目质量分必须在 0 到 1 之间")
    if value.difficulty not in range(1, 6) or value.target_difficulty not in range(1, 6):
        raise ValueError("题目难度必须在 1 到 5 之间")

    quality_component = value.quality_score * 70
    distance = abs(value.difficulty - value.target_difficulty)
    difficulty_component = max(0.0, 30.0 * (1 - distance / 4))
    return QuestionScore(
        total=round(quality_component + difficulty_component, 2),
        quality_component=round(quality_component, 2),
        difficulty_component=round(difficulty_component, 2),
    )


def calibrate_question_difficulty(
    question: GeneratedQuestion, evaluation: QuestionEvaluation
) -> DifficultyCalibration:
    """Calibrate level 1-5; level 5 uses explicit non-negotiable gates."""
    text = "\n".join((question.stem, question.analysis, question.scoring_criteria))
    high_features = tuple(
        name for name, pattern in HIGH_ORDER_FEATURES if re.search(pattern, text)
    )
    features = list(high_features)
    if evaluation.fusion_count >= 2:
        features.append(f"融合{evaluation.fusion_count}个知识点")
    if evaluation.reasoning_steps >= 3:
        features.append(f"至少{evaluation.reasoning_steps}层有效推理")
    has_turning_point = any(marker in question.analysis for marker in TURNING_POINT_MARKERS)
    if has_turning_point:
        features.append("解析包含关键转折")
    direct_formula = (
        len(question.analysis.strip()) < 60
        and evaluation.reasoning_steps < 2
        and len(high_features) == 0
    ) or bool(
        re.search(r"(?:直接|只需)?代入(?:公式|数据).{0,18}(?:即可|得)", question.analysis)
        and evaluation.reasoning_steps < 3
    )
    if not direct_formula:
        features.append("不能直接套用单一公式")

    if evaluation.reasoning_steps <= 1 and evaluation.fusion_count <= 1 and not high_features:
        level = 1
    elif evaluation.reasoning_steps <= 2 and evaluation.fusion_count <= 1 and not high_features:
        level = 2
    else:
        level = 3
    if evaluation.reasoning_steps >= 3 and (
        evaluation.fusion_count >= 2 or high_features
    ):
        level = max(level, 4)

    level_five_gate = (
        len(high_features) >= 2
        and evaluation.reasoning_steps >= 3
        and not direct_formula
        and has_turning_point
        and (evaluation.fusion_count >= 2 or len(high_features) >= 3)
    )
    if level_five_gate:
        level = 5

    reasons = [
        f"高阶特征{len(high_features)}项",
        f"推理层次{evaluation.reasoning_steps}",
        f"知识融合{evaluation.fusion_count}项",
    ]
    if direct_formula:
        reasons.append("可直接套用公式或解析步骤过短")
    if question.difficulty == 5 and not level_five_gate:
        missing = []
        if len(high_features) < 2:
            missing.append("至少2项高阶特征")
        if evaluation.reasoning_steps < 3:
            missing.append("至少3层有效推理")
        if direct_formula:
            missing.append("不得直接套用单一公式")
        if not has_turning_point:
            missing.append("解析中的关键转折")
        if evaluation.fusion_count < 2 and len(high_features) < 3:
            missing.append("知识融合或第3项高阶特征")
        reasons.append("第五档尚缺：" + "、".join(missing))
    return DifficultyCalibration(
        level=level,
        requested_level=question.difficulty,
        meets_requested=level >= question.difficulty,
        features=tuple(dict.fromkeys(features)),
        reasons=tuple(reasons),
        direct_formula=direct_formula,
    )


def rank_questions(
    questions: list[tuple[str, QuestionScoreInput]], minimum_score: float = 0
) -> list[tuple[str, QuestionScore]]:
    """Return eligible questions ordered by total score, highest first."""
    ranked = [(question_id, calculate_question_score(value)) for question_id, value in questions]
    return sorted(
        (item for item in ranked if item[1].total >= minimum_score),
        key=lambda item: (-item[1].total, item[0]),
    )
