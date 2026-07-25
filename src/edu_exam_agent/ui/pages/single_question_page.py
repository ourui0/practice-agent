"""Background single-question generation page."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import Engine

from edu_exam_agent.application.services.course_service import CourseService
from edu_exam_agent.application.services.knowledge_point_service import KnowledgePointService
from edu_exam_agent.application.services.provider_service import ProviderService
from edu_exam_agent.application.services.question_agent import (
    GenerationRequest,
    GenerationResult,
    QuestionGenerationAgent,
)
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


class QuestionWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, agent: QuestionGenerationAgent, request: GenerationRequest) -> None:
        super().__init__()
        self._agent = agent
        self._request = request

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(self._agent.generate(self._request))
        except Exception as exc:
            self.failed.emit(str(exc))


class SingleQuestionPage(QWidget):
    def __init__(
        self,
        courses: CourseService,
        points: KnowledgePointService,
        providers: ProviderService,
        retriever: FtsRetriever,
        engine: Engine,
    ) -> None:
        super().__init__()
        self._courses = courses
        self._points = points
        self._providers = providers
        self._retriever = retriever
        self._engine = engine
        self._thread = None
        self._worker = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 26, 34, 26)
        title = QLabel("单题生成")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        box = QGroupBox("生成要求")
        form = QFormLayout(box)
        self.course = QComboBox()
        self.course.currentIndexChanged.connect(self._reload_points)
        self.point = QComboBox()
        self.question_type = QComboBox()
        self.question_type.addItems(
            ("单项选择题", "多项选择题", "判断题", "填空题", "简答题", "计算题", "应用题")
        )
        self.difficulty = QSpinBox()
        self.difficulty.setRange(1, 5)
        self.difficulty.setValue(3)
        self.score = QSpinBox()
        self.score.setRange(1, 100)
        self.score.setValue(5)
        form.addRow("课程", self.course)
        form.addRow("已确认知识点", self.point)
        form.addRow("题型", self.question_type)
        form.addRow("难度", self.difficulty)
        form.addRow("分值", self.score)
        layout.addWidget(box)
        self.generate_button = QPushButton("根据教材生成并检查")
        self.generate_button.clicked.connect(self._generate)
        layout.addWidget(self.generate_button)
        self.status = QLabel("严格教材模式：没有教材依据时不会生成。")
        layout.addWidget(self.status)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.figure = QLabel()
        self.figure.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.figure.setMaximumHeight(300)
        self.figure.hide()
        layout.addWidget(self.figure)
        layout.addWidget(self.preview, 1)
        self.reload_courses()

    def reload_courses(self) -> None:
        current = self.course.currentData()
        self.course.blockSignals(True)
        self.course.clear()
        for course in self._courses.list():
            self.course.addItem(course.name, course.id)
        index = self.course.findData(current)
        if index >= 0:
            self.course.setCurrentIndex(index)
        self.course.blockSignals(False)
        self._reload_points()

    def _reload_points(self) -> None:
        self.point.clear()
        course_id = self.course.currentData()
        if course_id:
            for point in self._points.list(course_id):
                if point.status == "confirmed" and point.is_enabled:
                    self.point.addItem(point.name)
        if self.point.count() == 0:
            self.status.setText(
                "当前课程没有已确认知识点。请先提取知识点，并在知识点管理中确认。"
            )
            self.generate_button.setEnabled(False)
        else:
            self.status.setText("严格教材模式：没有教材依据时不会生成。")
            self.generate_button.setEnabled(True)

    def _generate(self) -> None:
        if not self.point.currentText():
            QMessageBox.information(self, "缺少知识点", "请先在知识点管理中确认知识点。")
            return
        try:
            provider, model = self._providers.create_provider()
        except Exception as exc:
            QMessageBox.warning(self, "模型未配置", str(exc))
            return
        agent = QuestionGenerationAgent(self._engine, self._retriever, provider, model)
        request = GenerationRequest(
            self.course.currentData(),
            self.point.currentText(),
            self.question_type.currentText(),
            self.difficulty.value(),
            self.score.value(),
            True,
        )
        self._thread = QThread(self)
        self._worker = QuestionWorker(agent, request)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.succeeded.connect(self._show_result)
        self._worker.failed.connect(self._show_error)
        self._worker.succeeded.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self.generate_button.setEnabled(False)
        self.status.setText("正在检索教材并生成题目……")
        self._thread.start()

    @Slot(object)
    def _show_result(self, result: GenerationResult) -> None:
        q = result.question
        options = "\n".join(f"{x.label}. {x.content}" for x in q.options)
        evidence = "\n".join(
            f"- {x.document_name} / {x.chapter_title} / 第{x.page_start}页：{x.excerpt}"
            for x in result.evidence
        )
        self.preview.setPlainText(
            f"题干：{q.stem}\n{options}\n\n答案：{q.answer}\n解析：{q.analysis}\n"
            f"质量分：{result.quality_score:.0%}\n推荐综合分：{result.recommendation_score}\n"
            f"难度校准：请求 {result.requested_difficulty} 档，"
            f"系统判定 {result.calibrated_difficulty} 档\n"
            f"教材边界：{'通过' if result.boundary_passed else '需复核'}\n\n教材依据：\n{evidence}"
        )
        if result.duplicate_matches:
            closest = result.duplicate_matches[0]
            self.preview.append(
                "\n重复检测：最接近题目 "
                f"{closest.question_id}，总相似度 {closest.breakdown.total:.0%}，"
                f"文本 {closest.breakdown.text:.0%}，数学结构 {closest.breakdown.math:.0%}，"
                f"母题 {closest.breakdown.model:.0%}。"
            )
        if result.figure_png:
            pixmap = QPixmap()
            pixmap.loadFromData(result.figure_png, "PNG")
            self.figure.setPixmap(
                pixmap.scaled(
                    560,
                    280,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.figure.show()
        else:
            self.figure.clear()
            self.figure.hide()
        self.status.setText(f"题目已保存，编号 {result.question_id}。")
        self.generate_button.setEnabled(True)

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self.status.setText("生成失败，未保存无效题目。")
        self.generate_button.setEnabled(True)
        QMessageBox.warning(self, "生成失败", message)
