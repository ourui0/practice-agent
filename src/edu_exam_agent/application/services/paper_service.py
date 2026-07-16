"""Question selection and DOCX export for exams and practice sets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.infrastructure.database.models import QuestionModel


@dataclass(frozen=True, slots=True)
class PaperRequest:
    course_id: int
    title: str
    question_types: tuple[str, ...]
    count: int
    target_difficulty: int | None = None
    minimum_score: float = 0
    include_answers: bool = True
    duration_minutes: int = 90
    document_id: int | None = None
    chapter_ids: tuple[int, ...] = ()

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("标题不能为空")
        if self.count < 1 or self.count > 200:
            raise ValueError("题目数量必须在 1 到 200 之间")
        if not self.question_types:
            raise ValueError("请至少选择一种题型")
        if self.target_difficulty is not None and self.target_difficulty not in range(1, 6):
            raise ValueError("目标难度必须在 1 到 5 之间")


@dataclass(frozen=True, slots=True)
class Paper:
    title: str
    questions: tuple[QuestionModel, ...]
    duration_minutes: int
    include_answers: bool

    @property
    def total_score(self) -> int:
        return sum(question.score for question in self.questions)


class PaperService:
    def __init__(self, bank: QuestionBankService) -> None:
        self._bank = bank

    def assemble(self, request: PaperRequest) -> Paper:
        request.validate()
        candidates = self._candidates(request)
        if len(candidates) < request.count:
            raise ValueError(
                f"符合条件且教材边界通过的题目只有 {len(candidates)} 道，"
                f"不足以生成 {request.count} 道题"
            )
        return Paper(
            request.title.strip(),
            tuple(candidates[: request.count]),
            request.duration_minutes,
            request.include_answers,
        )

    def available_count(self, request: PaperRequest) -> int:
        request.validate()
        return len(self._candidates(request))

    def _candidates(self, request: PaperRequest) -> list[QuestionModel]:
        candidates = [
            question
            for question in self._bank.list(
                course_id=request.course_id,
                minimum_score=request.minimum_score,
                document_id=request.document_id,
                chapter_ids=request.chapter_ids,
            )
            if question.question_type in request.question_types
            and question.boundary_passed
            and question.status in {"validated", "teacher_edited"}
        ]
        if request.target_difficulty is not None:
            candidates.sort(
                key=lambda question: (
                    abs(question.difficulty - request.target_difficulty),
                    -question.recommendation_score,
                    -question.id,
                )
            )
        return candidates

    def preview(self, paper: Paper, include_answers: bool = False) -> str:
        lines = [
            paper.title,
            (
                f"共 {len(paper.questions)} 题　总分 {paper.total_score} 分　"
                f"建议时长 {paper.duration_minutes} 分钟"
            ),
            "",
        ]
        for index, question in enumerate(paper.questions, 1):
            lines.append(f"{index}. {question.stem}（{question.score}分）")
            if self._bank.figure(question.id) is not None:
                lines.append("   [本题含配图，导出 Word 时自动插入]")
            for option in _options(question):
                lines.append(f"   {option['label']}. {option['content']}")
            if include_answers:
                lines.extend((f"   答案：{question.answer}", f"   解析：{question.analysis}"))
            lines.append("")
        return "\n".join(lines)

    def export_docx(self, paper: Paper, path: Path) -> Path:
        document = Document()
        section = document.sections[0]
        section.page_width = Cm(21)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(2.2)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.4)
        section.right_margin = Cm(2.4)
        section.header_distance = Cm(1.0)
        section.footer_distance = Cm(1.0)
        _configure_styles(document)
        _add_header_footer(section, paper.title)

        title = document.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run(paper.title)
        run.bold = True
        run.font.size = Pt(20)
        _set_run_font(run, "Microsoft YaHei")
        meta = document.add_paragraph(
            f"考试时间：{paper.duration_minutes} 分钟　　满分：{paper.total_score} 分"
        )
        meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        document.add_paragraph(
            "姓名：________________　班级：________________　得分：________________"
        )

        for index, question in enumerate(paper.questions, 1):
            paragraph = document.add_paragraph(style="Question")
            paragraph.add_run(f"{index}. {question.stem}").bold = True
            paragraph.add_run(f"（{question.score}分）")
            for option in _options(question):
                document.add_paragraph(
                    f"{option['label']}. {option['content']}", style="Option"
                )
            figure = self._bank.figure(question.id)
            if figure is not None:
                picture = document.add_picture(BytesIO(figure.png_data), width=Cm(12.5))
                picture.alignment = WD_ALIGN_PARAGRAPH.CENTER
            if question.question_type not in ("单项选择题", "多项选择题", "判断题"):
                document.add_paragraph("答：\n\n", style="AnswerSpace")

        if paper.include_answers:
            document.add_section(WD_SECTION.NEW_PAGE)
            document.add_heading("参考答案与解析", level=1)
            for index, question in enumerate(paper.questions, 1):
                answer = document.add_paragraph(style="Question")
                answer.add_run(f"{index}. 答案：").bold = True
                answer.add_run(question.answer)
                analysis = document.add_paragraph(style="Analysis")
                analysis.add_run("解析：").bold = True
                analysis.add_run(question.analysis)
                if question.scoring_criteria:
                    criteria = document.add_paragraph(style="Analysis")
                    criteria.add_run("评分标准：").bold = True
                    criteria.add_run(question.scoring_criteria)

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        document.save(path)
        return path


def _options(question: QuestionModel) -> list[dict[str, str]]:
    try:
        value = json.loads(question.options_json)
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _set_run_font(run, name: str) -> None:
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)


def _configure_styles(document: Document) -> None:
    normal = document.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(10.5)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    for name, left, first, after in (
        ("Question", 0, 0, 7),
        ("Option", 18, 0, 3),
        ("AnswerSpace", 18, 0, 6),
        ("Analysis", 18, 0, 5),
    ):
        style = document.styles.add_style(name, 1)
        style.font.name = "Microsoft YaHei"
        style.font.size = Pt(10.5)
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style.paragraph_format.left_indent = Pt(left)
        style.paragraph_format.first_line_indent = Pt(first)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.line_spacing = 1.15

    heading = document.styles["Heading 1"]
    heading.font.name = "Microsoft YaHei"
    heading.font.size = Pt(16)
    heading.font.color.rgb = RGBColor(31, 78, 121)
    heading._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")


def _add_header_footer(section, title: str) -> None:
    header = section.header.paragraphs[0]
    header.text = title
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in header.runs:
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(100, 100, 100)
        _set_run_font(run, "Microsoft YaHei")

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("第 ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    footer.add_run(" 页")
