"""Working exam and practice assembly pages backed by the question bank."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import Engine

from edu_exam_agent.application.services.batch_generation_service import (
    BatchGenerationRequest,
    BatchGenerationResult,
    BatchQuestionGenerationService,
)
from edu_exam_agent.application.services.course_service import CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.knowledge_point_service import KnowledgePointService
from edu_exam_agent.application.services.paper_service import Paper, PaperRequest, PaperService
from edu_exam_agent.application.services.provider_service import ProviderService
from edu_exam_agent.application.services.question_agent import QuestionGenerationAgent
from edu_exam_agent.infrastructure.retrieval import FtsRetriever

QUESTION_TYPES = (
    "单项选择题",
    "多项选择题",
    "判断题",
    "填空题",
    "简答题",
    "计算题",
    "应用题",
)


class BatchGenerationWorker(QObject):
    finished = Signal(object)

    def __init__(
        self, service: BatchQuestionGenerationService, request: BatchGenerationRequest
    ) -> None:
        super().__init__()
        self._service = service
        self._request = request

    @Slot()
    def run(self) -> None:
        self.finished.emit(self._service.generate(self._request))


class _PaperGenerationPage(QWidget):
    page_title = ""
    subtitle = ""
    default_count = 10
    default_types = ("单项选择题", "填空题")
    default_answers = True

    def __init__(
        self,
        courses: CourseService,
        documents: DocumentService,
        points: KnowledgePointService,
        providers: ProviderService,
        retriever: FtsRetriever,
        engine: Engine,
        papers: PaperService,
    ) -> None:
        super().__init__()
        self._courses = courses
        self._documents = documents
        self._points = points
        self._providers = providers
        self._retriever = retriever
        self._engine = engine
        self._papers = papers
        self._paper: Paper | None = None
        self._batch_thread: QThread | None = None
        self._batch_worker: BatchGenerationWorker | None = None
        self._pending_request: PaperRequest | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 26, 34, 26)
        title = QLabel(self.page_title)
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(title)
        self.status = QLabel(self.subtitle)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        settings = QGroupBox("组题条件")
        form = QFormLayout(settings)
        self.course = QComboBox()
        self.course.currentIndexChanged.connect(self._reload_documents)
        self.document = QComboBox()
        self.document.currentIndexChanged.connect(self._reload_chapters)
        self.scope = QComboBox()
        self.scope.addItems(("整门课程", "整本教材", "单个章节", "跨章节"))
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.chapters = QListWidget()
        self.chapters.setMinimumHeight(80)
        self.chapters.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.title_input = QComboBox()
        self.title_input.setEditable(True)
        self.title_input.addItem(self.page_title)
        self.count = QSpinBox()
        self.count.setRange(1, 200)
        self.count.setValue(self.default_count)
        self.difficulty = QComboBox()
        self.difficulty.addItems(("不限", "1 基础", "2 较易", "3 中等", "4 较难", "5 困难"))
        self.difficulty.setCurrentIndex(3)
        self.minimum = QSpinBox()
        self.minimum.setRange(0, 100)
        self.minimum.setValue(60)
        self.duration = QSpinBox()
        self.duration.setRange(10, 300)
        self.duration.setValue(90 if self.page_title == "试卷生成" else 30)
        self.answers = QCheckBox("导出参考答案与解析")
        self.answers.setChecked(self.default_answers)
        self.auto_supplement = QCheckBox("题库不足时自动使用 AI 补题（必需）")
        self.auto_supplement.setChecked(True)
        self.auto_supplement.setEnabled(False)
        form.addRow("课程", self.course)
        form.addRow("组题范围", self.scope)
        form.addRow("教材", self.document)
        form.addRow("章节", self.chapters)
        form.addRow("标题", self.title_input)
        form.addRow("题目数量", self.count)
        form.addRow("目标难度", self.difficulty)
        form.addRow("最低综合分", self.minimum)
        form.addRow("建议时长（分钟）", self.duration)
        form.addRow("答案", self.answers)
        form.addRow("自动补题", self.auto_supplement)
        layout.addWidget(settings)

        types = QGroupBox("题型（可多选）")
        type_layout = QHBoxLayout(types)
        self.type_checks: list[QCheckBox] = []
        for question_type in QUESTION_TYPES:
            check = QCheckBox(question_type)
            check.setChecked(question_type in self.default_types)
            self.type_checks.append(check)
            type_layout.addWidget(check)
        type_layout.addStretch(1)
        layout.addWidget(types)

        actions = QHBoxLayout()
        generate = QPushButton("从题库智能组题")
        generate.clicked.connect(self.generate)
        self.export_button = QPushButton("导出 Word")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export)
        actions.addWidget(generate)
        actions.addWidget(self.export_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("组题后将在这里显示预览。")
        layout.addWidget(self.preview, 1)
        self.reload_courses()
        self._scope_changed()

    def reload_courses(self) -> None:
        current = self.course.currentData()
        self.course.clear()
        for course in self._courses.list():
            self.course.addItem(course.name, course.id)
        index = self.course.findData(current)
        if index >= 0:
            self.course.setCurrentIndex(index)
        self._reload_documents()

    def _reload_documents(self) -> None:
        current = self.document.currentData() if hasattr(self, "document") else None
        self.document.clear()
        course_id = self.course.currentData()
        if course_id:
            for document in self._documents.list(course_id):
                if document.parse_status == "completed":
                    self.document.addItem(document.filename, document.id)
        index = self.document.findData(current)
        if index >= 0:
            self.document.setCurrentIndex(index)
        self._reload_chapters()

    def _reload_chapters(self) -> None:
        self.chapters.clear()
        document_id = self.document.currentData()
        if document_id:
            for chapter in self._documents.list_chapters(document_id):
                if not chapter.is_excluded:
                    self.chapters.addItem(chapter.title)
                    self.chapters.item(self.chapters.count() - 1).setData(
                        Qt.ItemDataRole.UserRole, chapter.id
                    )
        self._scope_changed()

    def _scope_changed(self) -> None:
        mode = self.scope.currentIndex()
        self.document.setEnabled(mode > 0)
        self.chapters.setEnabled(mode > 1)
        if mode <= 1:
            self.chapters.clearSelection()
        self.chapters.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
            if mode == 2
            else QListWidget.SelectionMode.ExtendedSelection
        )

    def generate(self) -> None:
        if self.course.currentData() is None:
            QMessageBox.information(self, "缺少课程", "请先创建课程并生成题目。")
            return
        selected_types = tuple(
            check.text() for check in self.type_checks if check.isChecked()
        )
        difficulty = self.difficulty.currentIndex() or None
        scope_mode = self.scope.currentIndex()
        document_id = self.document.currentData() if scope_mode > 0 else None
        chapter_ids = tuple(
            item.data(Qt.ItemDataRole.UserRole) for item in self.chapters.selectedItems()
        )
        if scope_mode > 0 and document_id is None:
            QMessageBox.information(self, "缺少教材", "当前课程没有已解析完成的教材。")
            return
        if scope_mode > 1 and not chapter_ids:
            QMessageBox.information(self, "缺少章节", "请选择需要组题的章节。")
            return
        request = PaperRequest(
            course_id=self.course.currentData(),
            title=self.title_input.currentText(),
            question_types=selected_types,
            count=self.count.value(),
            target_difficulty=difficulty,
            minimum_score=self.minimum.value(),
            include_answers=self.answers.isChecked(),
            duration_minutes=self.duration.value(),
            document_id=document_id,
            chapter_ids=chapter_ids,
        )
        try:
            available = self._papers.available_count(request)
        except ValueError as exc:
            QMessageBox.warning(self, "组题失败", str(exc))
            return
        if available < request.count:
            self._start_supplement(request, request.count - available)
            return
        try:
            self._paper = self._papers.assemble(request)
        except ValueError as exc:
            self._paper = None
            self.export_button.setEnabled(False)
            QMessageBox.warning(self, "组题失败", str(exc))
            return
        self._show_paper()

    def _show_paper(self) -> None:
        if self._paper is None:
            return
        self.preview.setPlainText(self._papers.preview(self._paper))
        self.export_button.setEnabled(True)
        self.status.setText(
            f"已选出 {len(self._paper.questions)} 道题，总分 {self._paper.total_score} 分。"
        )

    def _start_supplement(self, request: PaperRequest, missing: int) -> None:
        try:
            provider, model = self._providers.create_provider()
        except ValueError as exc:
            QMessageBox.warning(self, "模型未配置", str(exc))
            return
        scoped_chapters = request.chapter_ids
        if request.document_id and not scoped_chapters:
            scoped_chapters = tuple(
                chapter.id for chapter in self._documents.list_chapters(request.document_id)
            )
        points = tuple(
            point.name
            for point in self._points.list(request.course_id)
            if point.status == "confirmed"
            and point.is_enabled
            and (not scoped_chapters or point.chapter_id in scoped_chapters)
        )
        batch_request = BatchGenerationRequest(
            course_id=request.course_id,
            knowledge_points=points,
            question_types=request.question_types,
            count=missing,
            difficulty=request.target_difficulty or 3,
            document_id=request.document_id,
            chapter_ids=request.chapter_ids,
        )
        try:
            batch_request.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "无法自动补题", str(exc))
            return
        agent = QuestionGenerationAgent(
            self._engine, self._retriever, provider, model
        )
        self._pending_request = request
        self._batch_thread = QThread(self)
        self._batch_worker = BatchGenerationWorker(
            BatchQuestionGenerationService(agent), batch_request
        )
        self._batch_worker.moveToThread(self._batch_thread)
        self._batch_thread.started.connect(self._batch_worker.run)
        self._batch_worker.finished.connect(self._supplement_finished)
        self._batch_worker.finished.connect(self._batch_thread.quit)
        self._batch_thread.finished.connect(self._batch_worker.deleteLater)
        self._batch_thread.finished.connect(self._batch_thread.deleteLater)
        self.status.setText(f"题库不足，正在后台生成 {missing} 道补充题……")
        self._batch_thread.start()

    @Slot(object)
    def _supplement_finished(self, result: BatchGenerationResult) -> None:
        request = self._pending_request
        self._pending_request = None
        if request is None:
            return
        try:
            self._paper = self._papers.assemble(request)
        except ValueError as exc:
            details = "\n".join(result.errors[:3])
            QMessageBox.warning(self, "补题未完成", f"{exc}\n{details}".strip())
            return
        self._show_paper()

    def export(self) -> None:
        if self._paper is None:
            return
        suggested = f"{self._paper.title}.docx"
        filename, _ = QFileDialog.getSaveFileName(
            self, "导出 Word", suggested, "Word 文档 (*.docx)"
        )
        if not filename:
            return
        try:
            output = self._papers.export_docx(self._paper, Path(filename))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.status.setText(f"已导出：{output}")


class ExamGenerationPage(_PaperGenerationPage):
    page_title = "试卷生成"
    subtitle = "从真实题库选择教材边界通过且综合分较高的题目，生成正式试卷。"
    default_count = 20
    default_types = ("单项选择题", "填空题", "计算题", "应用题")


class PracticeGenerationPage(_PaperGenerationPage):
    page_title = "训练习题"
    subtitle = "按课程、难度和题型生成练习清单，可选择是否附带答案与解析。"
    default_count = 10
    default_types = ("单项选择题", "填空题")
