"""Textbook tracking page for learning guides and teaching plans."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import Engine

from edu_exam_agent.application.services.course_service import CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.knowledge_point_service import (
    KnowledgePointService,
)
from edu_exam_agent.application.services.provider_service import ProviderService
from edu_exam_agent.application.services.teaching_package_service import (
    TeachingPackageRequest,
    TeachingPackageResult,
    TeachingPackageService,
)
from edu_exam_agent.infrastructure.retrieval import FtsRetriever
from edu_exam_agent.ui.theme import PAGE_MARGINS
from edu_exam_agent.ui.widgets import StatusLabel


class TeachingPackageWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: TeachingPackageService,
        request: TeachingPackageRequest,
    ) -> None:
        super().__init__()
        self._service = service
        self._request = request

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(self._service.generate(self._request))
        except Exception as exc:
            self.failed.emit(str(exc))


class TeachingPackagePage(QWidget):
    """Teacher workflow for scoped, traceable preparation materials."""

    def __init__(
        self,
        courses: CourseService,
        documents: DocumentService,
        points: KnowledgePointService,
        providers: ProviderService,
        retriever: FtsRetriever,
        engine: Engine,
    ) -> None:
        super().__init__()
        self._courses = courses
        self._documents = documents
        self._points = points
        self._providers = providers
        self._retriever = retriever
        self._engine = engine
        self._thread: QThread | None = None
        self._worker: TeachingPackageWorker | None = None
        self._result: TeachingPackageResult | None = None
        self._service: TeachingPackageService | None = None
        self._loading_history = False
        self._build_ui()
        self.reload_courses()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        left, top, right, bottom = PAGE_MARGINS
        layout.setContentsMargins(left, top, right, bottom)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("教材追踪")
        title.setObjectName("pageTitle")
        subtitle = QLabel("依据教材知识点生成配套导学案和教案，并保留原文出处。")
        subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        heading.addLayout(title_box)
        heading.addStretch(1)
        self.history = QComboBox()
        self.history.setMinimumWidth(260)
        self.history.setAccessibleName("历史备课记录")
        self.history.currentIndexChanged.connect(self._load_history)
        heading.addWidget(QLabel("历史记录"))
        heading.addWidget(self.history)
        layout.addLayout(heading)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        form_scroll.setMinimumWidth(350)
        form_scroll.setMaximumWidth(460)
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 12, 0)
        form_layout.setSpacing(10)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.course = QComboBox()
        self.course.currentIndexChanged.connect(self._reload_documents)
        self.document = QComboBox()
        self.document.currentIndexChanged.connect(self._reload_chapters)
        self.chapters = QListWidget()
        self.chapters.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.chapters.setMinimumHeight(115)
        self.chapters.itemSelectionChanged.connect(self._reload_points)
        self.knowledge_points = QListWidget()
        self.knowledge_points.setMinimumHeight(150)
        self.knowledge_points.itemChanged.connect(self._update_generate_state)
        self.lesson_type = QComboBox()
        self.lesson_type.addItems(("新授课", "复习课", "练习课", "实验课", "探究课"))
        self.duration = QSpinBox()
        self.duration.setRange(20, 180)
        self.duration.setSuffix(" 分钟")
        self.duration.setValue(45)
        self.student_profile = QTextEdit()
        self.student_profile.setPlaceholderText("例如：基础差异较大，已学习相关前置知识")
        self.student_profile.setMaximumHeight(72)
        self.teaching_focus = QTextEdit()
        self.teaching_focus.setPlaceholderText("例如：突出概念形成过程和实际应用")
        self.teaching_focus.setMaximumHeight(72)
        self.requirements = QTextEdit()
        self.requirements.setPlaceholderText("可选：课堂活动、作业或分层教学要求")
        self.requirements.setMaximumHeight(72)

        form.addRow("课程", self.course)
        form.addRow("教材", self.document)
        form.addRow("章节", self.chapters)
        form.addRow("目标知识点", self.knowledge_points)
        form.addRow("课型", self.lesson_type)
        form.addRow("课时长度", self.duration)
        form.addRow("学生情况", self.student_profile)
        form.addRow("教学侧重点", self.teaching_focus)
        form.addRow("补充要求", self.requirements)
        form_layout.addLayout(form)

        self.generate_button = QPushButton("生成导学案和教案")
        self.generate_button.setProperty("primary", True)
        self.generate_button.clicked.connect(self._start_generation)
        form_layout.addWidget(self.generate_button)
        self.status = StatusLabel("严格教材模式：所有内容都会关联教材原文依据。")
        form_layout.addWidget(self.status)
        form_layout.addStretch(1)
        form_scroll.setWidget(form_widget)

        result_widget = QWidget()
        result_layout = QVBoxLayout(result_widget)
        result_layout.setContentsMargins(0, 0, 0, 0)
        action_row = QHBoxLayout()
        self.copy_button = QPushButton("复制当前内容")
        self.copy_button.clicked.connect(self._copy_current)
        self.copy_button.setEnabled(False)
        self.export_button = QPushButton("导出 Word")
        self.export_button.clicked.connect(self.export)
        self.export_button.setEnabled(False)
        self.delete_button = QPushButton("删除记录")
        self.delete_button.clicked.connect(self._delete_current)
        self.delete_button.setEnabled(False)
        action_row.addWidget(self.copy_button)
        action_row.addWidget(self.export_button)
        action_row.addWidget(self.delete_button)
        action_row.addStretch(1)
        result_layout.addLayout(action_row)

        self.tabs = QTabWidget()
        self.guide_preview = self._preview()
        self.plan_preview = self._preview()
        self.tracking_preview = self._preview()
        self.tabs.addTab(self.guide_preview, "导学案")
        self.tabs.addTab(self.plan_preview, "教案")
        self.tabs.addTab(self.tracking_preview, "教材依据")
        result_layout.addWidget(self.tabs, 1)

        splitter.addWidget(form_scroll)
        splitter.addWidget(result_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes((390, 760))
        layout.addWidget(splitter, 1)

    @staticmethod
    def _preview() -> QPlainTextEdit:
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        return preview

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
        self._reload_documents()

    def _reload_documents(self) -> None:
        current = self.document.currentData()
        self.document.blockSignals(True)
        self.document.clear()
        course_id = self.course.currentData()
        if course_id:
            for descriptor in self._documents.list_descriptors(course_id):
                if descriptor.health.ready_for_generation:
                    self.document.addItem(descriptor.document.filename, descriptor.document.id)
        index = self.document.findData(current)
        if index >= 0:
            self.document.setCurrentIndex(index)
        self.document.blockSignals(False)
        self._reload_chapters()
        self._reload_history()

    def _reload_chapters(self) -> None:
        current_ids = set(self._selected_chapter_ids())
        self.chapters.blockSignals(True)
        self.chapters.clear()
        document_id = self.document.currentData()
        if document_id:
            for chapter in self._documents.list_chapters(document_id):
                item = QListWidgetItem(chapter.title)
                item.setData(Qt.ItemDataRole.UserRole, chapter.id)
                self.chapters.addItem(item)
                if chapter.id in current_ids:
                    item.setSelected(True)
            if not self.chapters.selectedItems() and self.chapters.count():
                self.chapters.item(0).setSelected(True)
                self.chapters.setCurrentRow(0)
        self.chapters.blockSignals(False)
        self._reload_points()

    def _reload_points(self) -> None:
        checked = set(self._checked_point_ids())
        selected_chapters = set(self._selected_chapter_ids())
        self.knowledge_points.blockSignals(True)
        self.knowledge_points.clear()
        course_id = self.course.currentData()
        if course_id:
            for point in self._points.list(course_id):
                if (
                    point.status != "confirmed"
                    or not point.is_enabled
                    or (
                        selected_chapters
                        and point.chapter_id is not None
                        and point.chapter_id not in selected_chapters
                    )
                ):
                    continue
                item = QListWidgetItem(point.name)
                item.setData(Qt.ItemDataRole.UserRole, point.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked if point.id in checked else Qt.CheckState.Unchecked
                )
                item.setToolTip(point.description or point.teacher_note)
                self.knowledge_points.addItem(item)
        if not checked and self.knowledge_points.count():
            self.knowledge_points.item(0).setCheckState(Qt.CheckState.Checked)
        self.knowledge_points.blockSignals(False)
        self._update_generate_state()

    def _reload_history(self) -> None:
        current = self.history.currentData()
        self._loading_history = True
        self.history.clear()
        self.history.addItem("选择已生成内容", None)
        course_id = self.course.currentData()
        if course_id:
            service = self._history_service()
            for row in service.list_history(course_id):
                timestamp = row.created_at.strftime("%m-%d %H:%M")
                self.history.addItem(f"{row.title} · {timestamp}", row.id)
        index = self.history.findData(current)
        self.history.setCurrentIndex(index if index >= 0 else 0)
        self._loading_history = False

    def _history_service(self) -> TeachingPackageService:
        if self._service is not None:
            return self._service

        class _UnavailableProvider:
            def generate_json(self, _system_prompt: str, _user_prompt: str) -> dict:
                raise RuntimeError("当前操作不需要调用模型")

            def chat(self, _messages):
                raise RuntimeError("当前操作不需要调用模型")

            def chat_with_tools(self, _messages, _tools):
                raise RuntimeError("当前操作不需要调用模型")

        return TeachingPackageService(self._engine, self._retriever, _UnavailableProvider(), "")

    def _selected_chapter_ids(self) -> tuple[int, ...]:
        return tuple(
            int(item.data(Qt.ItemDataRole.UserRole)) for item in self.chapters.selectedItems()
        )

    def _checked_point_ids(self) -> tuple[int, ...]:
        return tuple(
            int(item.data(Qt.ItemDataRole.UserRole))
            for row in range(self.knowledge_points.count())
            if (item := self.knowledge_points.item(row)).checkState() == Qt.CheckState.Checked
        )

    def _update_generate_state(self) -> None:
        self.generate_button.setEnabled(self._thread is None)
        if not self.course.currentData():
            self.status.setText("还没有课程，请先在课程管理中创建课程。")
        elif not self.document.currentData():
            self.status.setText("当前课程没有可用于生成的教材，请先上传并解析教材。")
        elif not self._selected_chapter_ids():
            self.status.setText("请选择需要备课的教材章节。")
        elif not self._checked_point_ids():
            self.status.setText("请勾选至少一个已确认知识点。")
        elif self._thread is None:
            self.status.setText("严格教材模式：所有内容都会关联教材原文依据。")

    def _start_generation(self) -> None:
        course_id = self.course.currentData()
        document_id = self.document.currentData()
        chapter_ids = self._selected_chapter_ids()
        point_ids = self._checked_point_ids()
        if course_id is None:
            QMessageBox.information(self, "缺少课程", "请先在课程管理中创建课程。")
            return
        if document_id is None:
            QMessageBox.information(
                self,
                "缺少教材",
                "当前课程没有可用于生成的教材，请先上传并完成解析。",
            )
            return
        if not chapter_ids:
            QMessageBox.information(self, "缺少章节", "请选择需要备课的教材章节。")
            return
        if not point_ids:
            QMessageBox.information(
                self,
                "缺少知识点",
                "请勾选至少一个已确认知识点。",
            )
            return
        try:
            request = TeachingPackageRequest(
                course_id=int(course_id),
                document_id=int(document_id),
                chapter_ids=chapter_ids,
                knowledge_point_ids=point_ids,
                lesson_type=self.lesson_type.currentText(),
                lesson_duration_minutes=self.duration.value(),
                student_profile=self.student_profile.toPlainText().strip(),
                teaching_focus=self.teaching_focus.toPlainText().strip(),
                additional_requirements=self.requirements.toPlainText().strip(),
            )
            request.validate()
            provider, model_name = self._providers.create_provider(timeout=180)
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "暂时无法生成", str(exc))
            return
        self._service = TeachingPackageService(self._engine, self._retriever, provider, model_name)
        self._thread = QThread(self)
        self._worker = TeachingPackageWorker(self._service, request)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.succeeded.connect(self._show_result)
        self._worker.failed.connect(self._show_error)
        self._worker.succeeded.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._generation_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self.generate_button.setEnabled(False)
        self.generate_button.setText("正在生成…")
        self.status.setText("正在检索教材、生成两份内容并核对教材出处…")
        self._thread.start()

    @Slot()
    def _generation_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.generate_button.setText("生成导学案和教案")
        self._update_generate_state()

    @Slot(object)
    def _show_result(self, result: TeachingPackageResult) -> None:
        self._result = result
        self.guide_preview.setPlainText(
            TeachingPackageService.render_learning_guide(result.payload)
        )
        self.plan_preview.setPlainText(TeachingPackageService.render_teaching_plan(result.payload))
        self.tracking_preview.setPlainText(
            TeachingPackageService.render_material_tracking(result.payload, result.evidence)
        )
        self.copy_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        status_text = {
            "complete": "完整",
            "partial": "部分完成，请查看教材依据中的提示",
            "insufficient": "教材证据不足",
        }.get(result.status, result.status)
        self.status.setText(f"已保存备课记录，生成状态：{status_text}。")
        self._reload_history()
        index = self.history.findData(result.record_id)
        if index >= 0:
            self._loading_history = True
            self.history.setCurrentIndex(index)
            self._loading_history = False

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self.status.setText("生成失败，未保存无效内容。")
        QMessageBox.warning(self, "生成失败", message)

    def _load_history(self) -> None:
        if self._loading_history:
            return
        record_id = self.history.currentData()
        if record_id is None:
            return
        try:
            self._show_result(self._history_service().load(int(record_id)))
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "无法打开记录", str(exc))

    def _copy_current(self) -> None:
        preview = self.tabs.currentWidget()
        if isinstance(preview, QPlainTextEdit):
            QApplication.clipboard().setText(preview.toPlainText())
            self.status.setText(f"已复制“{self.tabs.tabText(self.tabs.currentIndex())}”。")

    def export(self) -> None:
        if self._result is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出备课资料",
            f"{self._result.title}.docx",
            "Word 文档 (*.docx)",
        )
        if not filename:
            return
        try:
            output = self._history_service().export_docx(self._result, Path(filename))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.status.setText(f"已导出：{output}")

    def _delete_current(self) -> None:
        if self._result is None:
            return
        answer = QMessageBox.question(
            self,
            "删除备课记录",
            f"确定删除“{self._result.title}”吗？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._history_service().delete(self._result.record_id)
        self._result = None
        for preview in (self.guide_preview, self.plan_preview, self.tracking_preview):
            preview.clear()
        self.copy_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.status.setText("备课记录已删除。")
        self._reload_history()
