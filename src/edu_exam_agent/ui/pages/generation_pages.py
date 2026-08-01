"""Working exam and practice assembly pages backed by the question bank."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
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
from edu_exam_agent.application.services.question_types import (
    QUESTION_TYPE_LABELS,
    QUESTION_TYPE_ORDER,
)
from edu_exam_agent.infrastructure.retrieval import FtsRetriever
from edu_exam_agent.ui.theme import PAGE_MARGINS
from edu_exam_agent.ui.widgets import StatusLabel


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
    default_type_counts = {
        "单项选择题": 3,
        "填空题": 3,
        "计算题": 2,
        "应用题": 2,
    }
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
        self._syncing_outline = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        self.page_scroll = QScrollArea()
        self.page_scroll.setObjectName("paperGenerationScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.page_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("paperGenerationContent")
        layout = QVBoxLayout(self.scroll_content)
        left, top, right, bottom = PAGE_MARGINS
        layout.setContentsMargins(left, top, right, bottom)
        layout.setSpacing(14)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.page_scroll.setWidget(self.scroll_content)
        root_layout.addWidget(self.page_scroll)

        title = QLabel(self.page_title)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.status_label = StatusLabel(self.subtitle)
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        content = QWidget()
        left_layout = QVBoxLayout(content)
        left_layout.setContentsMargins(0, 0, 18, 0)
        left_layout.setSpacing(14)
        left_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        self.course = QComboBox()
        self.course.currentIndexChanged.connect(self._reload_documents)
        self.document = QComboBox()
        self.document.currentIndexChanged.connect(self._reload_chapters)
        self.scope = QComboBox()
        self.scope.addItems(("整门课程", "整本教材", "单个章节", "跨章节"))
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.chapter_button = QPushButton("请选择章节")
        self.chapter_button.setObjectName("ChapterSelectButton")
        self.chapter_button.setFixedHeight(40)
        self.chapter_button.clicked.connect(self._show_chapter_popup)

        self.chapter_popup = QFrame(self, Qt.WindowType.Popup)
        self.chapter_popup.setObjectName("ChapterPopup")
        popup_layout = QVBoxLayout(self.chapter_popup)
        popup_layout.setContentsMargins(16, 16, 16, 16)
        popup_layout.setSpacing(12)
        popup_columns = QHBoxLayout()
        popup_columns.setSpacing(16)

        major_column = QVBoxLayout()
        major_column.setContentsMargins(0, 0, 0, 0)
        major_column.setSpacing(6)
        major_label = QLabel("大章")
        major_label.setProperty("chapterColumnLabel", True)
        self.chapters = QListWidget()
        self.chapters.setObjectName("chapterMajorList")
        self.chapters.setMinimumWidth(240)
        self.chapters.setWordWrap(True)
        self.chapters.setUniformItemSizes(False)
        self.chapters.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chapters.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chapters.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.chapters.itemSelectionChanged.connect(self._chapter_selection_changed)
        major_column.addWidget(major_label)
        major_column.addWidget(self.chapters)

        section_column = QVBoxLayout()
        section_column.setContentsMargins(0, 0, 0, 0)
        section_column.setSpacing(6)
        section_label = QLabel("所含小节")
        section_label.setProperty("chapterColumnLabel", True)
        self.chapter_sections = QListWidget()
        self.chapter_sections.setObjectName("chapterSectionList")
        self.chapter_sections.setMinimumWidth(260)
        self.chapter_sections.setWordWrap(True)
        self.chapter_sections.setUniformItemSizes(False)
        self.chapter_sections.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.chapter_sections.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.chapter_sections.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.chapter_sections.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        section_column.addWidget(section_label)
        section_column.addWidget(self.chapter_sections)
        popup_columns.addLayout(major_column, 1)
        popup_columns.addLayout(section_column, 1)
        popup_layout.addLayout(popup_columns)
        self.title_input = QComboBox()
        self.title_input.setEditable(True)
        default_title = f"{self.page_title} - {date.today().isoformat()}"
        self.title_input.addItem(default_title)
        self.title_input.setAccessibleName("试卷标题")
        self.count = QSpinBox()
        self.count.setRange(0, 400)
        self.count.setReadOnly(True)
        self.difficulty = QComboBox()
        self.difficulty.addItems(("不限", "1 基础", "2 较易", "3 中等", "4 较难", "5 困难"))
        self.difficulty.setCurrentIndex(3)
        self.minimum = QSpinBox()
        self.minimum.setRange(0, 100)
        self.minimum.setValue(60)
        self.duration = QSpinBox()
        self.duration.setRange(10, 300)
        self.duration.setValue(90 if self.page_title == "试卷生成" else 30)
        for spin_box in (self.count, self.minimum, self.duration):
            spin_box.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin_box.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        self.type_count_spins: dict[str, QSpinBox] = {}
        for question_type in QUESTION_TYPE_ORDER:
            spin = QSpinBox()
            spin.setRange(0, 100)
            spin.setValue(self.default_type_counts.get(question_type, 0))
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self.type_count_spins[question_type] = spin
        for spin in self.type_count_spins.values():
            spin.valueChanged.connect(self._sync_total_count)
        self._sync_total_count()
        self.answers = QCheckBox("导出参考答案与解析")
        self.answers.setChecked(self.default_answers)
        self.auto_supplement = QCheckBox("题库不足时自动使用 AI 补题（必需）")
        self.auto_supplement.setChecked(True)
        self.auto_supplement.setEnabled(False)

        def create_form_item(label_text: str, widget: QWidget) -> QWidget:
            item_widget = QWidget()
            item_widget.setObjectName("FormItem")
            item_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            item_layout = QVBoxLayout(item_widget)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(6)
            label = QLabel(label_text)
            label.setProperty("formLabel", True)
            label.setFixedHeight(18)
            widget.setFixedHeight(40)
            item_layout.addWidget(label)
            item_layout.addWidget(widget)
            return item_widget

        settings = QFrame()
        settings.setObjectName("OutlineCard")
        settings.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(24, 24, 24, 24)
        settings_layout.setSpacing(16)
        settings_title = QLabel("组题条件")
        settings_title.setObjectName("cardTitle")
        settings_layout.addWidget(settings_title)

        form_grid = QGridLayout()
        form_grid.setContentsMargins(0, 0, 0, 0)
        form_grid.setHorizontalSpacing(32)
        form_grid.setVerticalSpacing(24)
        form_grid.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        form_grid.setColumnStretch(0, 1)
        form_grid.setColumnStretch(1, 1)
        form_grid.addWidget(create_form_item("课程", self.course), 0, 0)
        form_grid.addWidget(create_form_item("组题范围", self.scope), 0, 1)
        form_grid.addWidget(create_form_item("教材", self.document), 1, 0)
        form_grid.addWidget(create_form_item("章节", self.chapter_button), 1, 1)
        form_grid.addWidget(create_form_item("试卷标题", self.title_input), 2, 0)
        form_grid.addWidget(create_form_item("题目数量", self.count), 2, 1)
        form_grid.addWidget(create_form_item("最低综合分", self.minimum), 3, 0)
        form_grid.addWidget(create_form_item("目标难度", self.difficulty), 3, 1)
        form_grid.addWidget(create_form_item("建议时长（分钟）", self.duration), 4, 1)

        checkbox_layout = QHBoxLayout()
        checkbox_layout.setContentsMargins(0, 2, 0, 0)
        checkbox_layout.setSpacing(28)
        checkbox_layout.addWidget(self.answers)
        checkbox_layout.addWidget(self.auto_supplement)
        checkbox_layout.addStretch(1)
        form_grid.addLayout(checkbox_layout, 5, 0, 1, 2)
        settings_layout.addLayout(form_grid)
        left_layout.addWidget(settings)

        types = QFrame()
        self.type_count_card = types
        types.setObjectName("OutlineCard")
        types.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        type_layout = QVBoxLayout(types)
        type_layout.setContentsMargins(24, 20, 24, 24)
        type_layout.setSpacing(14)
        type_title = QLabel("题型与数量")
        type_title.setObjectName("cardTitle")
        type_layout.addWidget(type_title)
        type_grid = QGridLayout()
        type_grid.setContentsMargins(0, 0, 0, 0)
        type_grid.setHorizontalSpacing(24)
        type_grid.setVerticalSpacing(16)
        type_grid.setColumnStretch(0, 1)
        type_grid.setColumnStretch(1, 1)
        for index, question_type in enumerate(QUESTION_TYPE_ORDER):
            label = f"{QUESTION_TYPE_LABELS[question_type]}数量"
            type_grid.addWidget(
                create_form_item(label, self.type_count_spins[question_type]),
                index // 2,
                index % 2,
            )
        type_layout.addLayout(type_grid)
        left_layout.addWidget(types)

        actions = QHBoxLayout()
        self.generate_btn = QPushButton("从题库智能组题")
        self.generate_btn.clicked.connect(self.generate)
        self.generate_btn.setAccessibleName("从题库智能组题")
        self.export_button = QPushButton("导出 Word")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export)
        self.export_button.setAccessibleName("导出 Word")
        self.cancel_supplement_btn = QPushButton("取消补题")
        self.cancel_supplement_btn.clicked.connect(self._cancel_supplement)
        self.cancel_supplement_btn.hide()
        actions.addWidget(self.generate_btn)
        actions.addWidget(self.export_button)
        actions.addWidget(self.cancel_supplement_btn)
        actions.addStretch(1)
        left_layout.addLayout(actions)
        # Connect type count changes to update button states
        for spin in self.type_count_spins.values():
            spin.valueChanged.connect(self._update_generate_button_state)
        self.course.currentIndexChanged.connect(self._update_generate_button_state)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(120)
        self.preview.setPlaceholderText("组题后将在这里显示预览。")
        left_layout.addWidget(self.preview, 1)

        drawer = QFrame()
        drawer.setObjectName("OutlineDrawer")
        drawer.setMinimumWidth(320)
        drawer.setMaximumWidth(320)
        drawer_layout = QVBoxLayout(drawer)
        drawer_layout.setContentsMargins(20, 20, 16, 18)
        drawer_layout.setSpacing(10)
        drawer_title = QLabel("试卷结构大纲")
        drawer_title.setStyleSheet("font-size:17px; font-weight:600; color:#1F1F1F;")
        drawer_hint = QLabel("拖动题目可调整顺序，预览与 Word 导出将同步更新。")
        drawer_hint.setObjectName("secondaryText")
        drawer_hint.setWordWrap(True)
        self.outline = QListWidget()
        self.outline.setObjectName("paperOutline")
        self.outline.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.outline.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.outline.setDragEnabled(True)
        self.outline.setAcceptDrops(True)
        self.outline.setDropIndicatorShown(True)
        self.outline.setMinimumHeight(120)
        self.outline.model().rowsMoved.connect(self._outline_reordered)
        drawer_layout.addWidget(drawer_title)
        drawer_layout.addWidget(drawer_hint)
        drawer_layout.addWidget(self.outline, 1)

        splitter.addWidget(content)
        splitter.addWidget(drawer)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes((760, 320))
        splitter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        layout.addWidget(splitter)
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
            if hasattr(self._documents, "list_descriptors"):
                descriptors = self._documents.list_descriptors(course_id)
                descriptors.sort(
                    key=lambda item: not item.health.ready_for_generation
                )
                for descriptor in descriptors:
                    document = descriptor.document
                    if descriptor.health.ready_for_generation:
                        text = f"{document.filename} · {descriptor.identity.display_name}"
                        data = document.id
                    else:
                        text = f"⚠ {document.filename} · {descriptor.health.message}"
                        data = None
                    self.document.addItem(text, data)
                    self.document.setItemData(
                        self.document.count() - 1,
                        descriptor.health.message,
                        Qt.ItemDataRole.ToolTipRole,
                    )
                    if not descriptor.health.ready_for_generation:
                        item = self.document.model().item(self.document.count() - 1)
                        if item is not None:
                            item.setEnabled(False)
            else:
                for document in self._documents.list(course_id):
                    if document.parse_status == "completed":
                        self.document.addItem(document.filename, document.id)
        index = self.document.findData(current)
        if index >= 0:
            self.document.setCurrentIndex(index)
        self._reload_chapters()

    def _reload_chapters(self) -> None:
        self.chapters.blockSignals(True)
        self.chapters.clear()
        self.chapter_sections.clear()
        document_id = self.document.currentData()
        if document_id:
            for chapter in self._documents.chapter_outline(document_id):
                item = QListWidgetItem(chapter.title)
                item.setData(Qt.ItemDataRole.UserRole, chapter.chapter_ids)
                item.setData(
                    Qt.ItemDataRole.UserRole + 1,
                    tuple(section.title for section in chapter.sections),
                )
                self.chapters.addItem(item)
        self.chapters.blockSignals(False)
        self._chapter_selection_changed()
        self._scope_changed()

    def _selected_chapter_items(self) -> list[QListWidgetItem]:
        return [
            self.chapters.item(index)
            for index in range(self.chapters.count())
            if self.chapters.item(index).isSelected()
        ]

    def _chapter_selection_changed(self) -> None:
        self.chapter_sections.clear()
        selected = self._selected_chapter_items()
        for chapter_index, item in enumerate(selected):
            if len(selected) > 1:
                heading = QListWidgetItem(item.text())
                heading.setFlags(heading.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                heading_font = heading.font()
                heading_font.setBold(True)
                heading.setFont(heading_font)
                heading.setForeground(QColor("#5F6368"))
                self.chapter_sections.addItem(heading)
            sections = item.data(Qt.ItemDataRole.UserRole + 1) or ()
            for title in sections:
                section = QListWidgetItem(str(title))
                section.setFlags(section.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.chapter_sections.addItem(section)
            if chapter_index < len(selected) - 1:
                separator = QListWidgetItem("")
                separator.setFlags(separator.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.chapter_sections.addItem(separator)
        self._update_chapter_button_text()

    def _update_chapter_button_text(self) -> None:
        mode = self.scope.currentIndex()
        selected = self._selected_chapter_items()
        if mode <= 1:
            text = "无需选择章节"
        elif not selected:
            text = "请选择章节"
        elif mode == 2:
            text = selected[0].text()
        else:
            text = f"已选择 {len(selected)} 个章节"
        self.chapter_button.setText(text)

    def _show_chapter_popup(self) -> None:
        if not self.chapter_button.isEnabled() or not self.chapters.count():
            return
        screen_rect = self.chapter_button.screen().availableGeometry()
        screen_margin = 8
        available_width = max(1, screen_rect.width() - screen_margin * 2)
        available_height = max(1, screen_rect.height() - screen_margin * 2)
        popup_width = min(
            max(560, self.chapter_button.width()),
            available_width,
        )
        popup_height = min(380, available_height)
        self.chapter_popup.resize(popup_width, popup_height)

        below = self.chapter_button.mapToGlobal(self.chapter_button.rect().bottomLeft())
        above = self.chapter_button.mapToGlobal(self.chapter_button.rect().topLeft())
        min_x = screen_rect.left() + screen_margin
        max_x = screen_rect.right() - popup_width - screen_margin + 1
        popup_x = max(min_x, min(below.x(), max_x))
        max_y = screen_rect.bottom() - popup_height - screen_margin + 1
        if below.y() <= max_y:
            popup_y = below.y()
        else:
            popup_y = max(screen_rect.top() + screen_margin, above.y() - popup_height)
        self.chapter_popup.move(popup_x, popup_y)
        self.chapter_popup.show()
        self.chapter_popup.raise_()
        self.chapters.setFocus()

    def _selected_chapter_ids(self) -> tuple[int, ...]:
        selected: list[int] = []
        for item in self._selected_chapter_items():
            value = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(value, (tuple, list)):
                selected.extend(int(chapter_id) for chapter_id in value)
            elif isinstance(value, int):
                selected.append(value)
        return tuple(dict.fromkeys(selected))

    def _scope_changed(self) -> None:
        mode = self.scope.currentIndex()
        self.document.setEnabled(mode > 0)
        self.chapter_button.setEnabled(mode > 1 and self.chapters.count() > 0)
        if mode <= 1:
            self.chapter_popup.hide()
            self.chapters.clearSelection()
        selection_mode = (
            QAbstractItemView.SelectionMode.SingleSelection
            if mode == 2
            else QAbstractItemView.SelectionMode.MultiSelection
        )
        self.chapters.setSelectionMode(selection_mode)
        selected = self._selected_chapter_items()
        if mode == 2 and len(selected) > 1:
            keep = selected[0]
            self.chapters.blockSignals(True)
            self.chapters.clearSelection()
            keep.setSelected(True)
            self.chapters.setCurrentItem(keep)
            self.chapters.blockSignals(False)
        self._chapter_selection_changed()

    def _sync_total_count(self) -> None:
        if not hasattr(self, "type_count_spins"):
            return
        self.count.setValue(
            sum(spin.value() for spin in self.type_count_spins.values())
        )

    def _type_counts(self) -> tuple[tuple[str, int], ...]:
        return tuple(
            (question_type, self.type_count_spins[question_type].value())
            for question_type in QUESTION_TYPE_ORDER
            if self.type_count_spins[question_type].value() > 0
        )

    @staticmethod
    def _type_summary(type_counts: tuple[tuple[str, int], ...]) -> str:
        return "、".join(
            f"{QUESTION_TYPE_LABELS[question_type]}{count}道"
            for question_type, count in type_counts
        )

    def _update_generate_button_state(self) -> None:
        """Enable generate only when course is selected and at least one type has count > 0."""
        has_course = self.course.currentData() is not None
        has_types = any(spin.value() > 0 for spin in self.type_count_spins.values())
        self.generate_btn.setEnabled(has_course and has_types)

    def _cancel_supplement(self) -> None:
        if self._batch_thread is not None and self._batch_thread.isRunning():
            self._batch_thread.quit()
            self._batch_thread.wait(1000)
        self._batch_thread = None
        self._batch_worker = None
        self._pending_request = None
        self.cancel_supplement_btn.hide()
        self.generate_btn.setEnabled(True)
        self.status_label.setText("补题操作已取消。")

    def generate(self) -> None:
        if self.course.currentData() is None:
            QMessageBox.information(self, "缺少课程", "请先创建课程并生成题目。")
            return
        type_counts = self._type_counts()
        if not type_counts:
            QMessageBox.information(self, "缺少题型", "请至少将一种题型数量设为1。")
            return
        selected_types = tuple(question_type for question_type, _ in type_counts)
        difficulty = self.difficulty.currentIndex() or None
        scope_mode = self.scope.currentIndex()
        document_id = self.document.currentData() if scope_mode > 0 else None
        chapter_ids = self._selected_chapter_ids()
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
            question_type_counts=type_counts,
        )
        try:
            available_by_type = self._papers.available_count_by_type(request)
        except ValueError as exc:
            QMessageBox.warning(self, "组题失败", str(exc))
            return
        shortages = {
            question_type: max(
                0, count - available_by_type.get(question_type, 0)
            )
            for question_type, count in type_counts
        }
        shortages = {
            question_type: count
            for question_type, count in shortages.items()
            if count > 0
        }
        if shortages:
            self._start_supplement(request, shortages)
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
        self._syncing_outline = True
        self.outline.clear()
        for index, question in enumerate(self._paper.questions, 1):
            item = QListWidgetItem(
                f"⋮⋮  {index}.  {question.question_type}  ·  {question.score} 分\n"
                f"      {question.stem[:34]}{'…' if len(question.stem) > 34 else ''}"
            )
            item.setData(Qt.ItemDataRole.UserRole, question.id)
            self.outline.addItem(item)
        self._syncing_outline = False
        self.export_button.setEnabled(True)
        counts: dict[str, int] = {}
        for question in self._paper.questions:
            counts[question.question_type] = counts.get(question.question_type, 0) + 1
        ordered_counts = tuple(
            (question_type, counts[question_type])
            for question_type in QUESTION_TYPE_ORDER
            if counts.get(question_type, 0) > 0
        )
        self.status_label.setText(
            f"已生成{len(self._paper.questions)}道题：{self._type_summary(ordered_counts)}。"
        )

    def load_paper(self, history_id: int) -> None:
        """Restore and preview a paper selected from the AI chat page."""
        self._paper = self._papers.load(history_id)
        self._show_paper()

    def _outline_reordered(self, *_args) -> None:  # type: ignore[no-untyped-def]
        if self._syncing_outline or self._paper is None:
            return
        by_id = {question.id: question for question in self._paper.questions}
        ordered = tuple(
            by_id[self.outline.item(row).data(Qt.ItemDataRole.UserRole)]
            for row in range(self.outline.count())
        )
        self._paper = Paper(
            self._paper.title,
            ordered,
            self._paper.duration_minutes,
            self._paper.include_answers,
            self._paper.history_id,
        )
        self.preview.setPlainText(self._papers.preview(self._paper))
        self.status_label.setText("题目顺序已更新，预览与导出内容已同步。")

    def _start_supplement(
        self, request: PaperRequest, shortages: dict[str, int]
    ) -> None:
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
            question_types=tuple(shortages),
            count=sum(shortages.values()),
            difficulty=request.target_difficulty or 3,
            document_id=request.document_id,
            chapter_ids=request.chapter_ids,
            question_type_counts=tuple(
                (question_type, shortages[question_type])
                for question_type in QUESTION_TYPE_ORDER
                if shortages.get(question_type, 0) > 0
            ),
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
        shortage_text = "；".join(
            f"{QUESTION_TYPE_LABELS[question_type]}还缺{count}道"
            for question_type, count in batch_request.question_type_counts
        )
        self.generate_btn.setEnabled(False)
        self.cancel_supplement_btn.show()
        self.status_label.setText(
            f"当前无法完成组题：{shortage_text}。正在按缺口自动补题……"
        )
        self._batch_thread.start()

    @Slot(object)
    def _supplement_finished(self, result: BatchGenerationResult) -> None:
        self.cancel_supplement_btn.hide()
        self.generate_btn.setEnabled(True)
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
        self.status_label.setText(f"已导出：{output}")


class ExamGenerationPage(_PaperGenerationPage):
    page_title = "试卷生成"
    subtitle = "从真实题库选择教材边界通过且综合分较高的题目，生成正式试卷。"
    default_count = 20
    default_types = ("单项选择题", "填空题", "计算题", "应用题")
    default_type_counts = {
        "单项选择题": 5,
        "填空题": 5,
        "计算题": 5,
        "应用题": 5,
    }


class PracticeGenerationPage(_PaperGenerationPage):
    page_title = "训练习题"
    subtitle = "按课程、难度和题型生成练习清单，可选择是否附带答案与解析。"
    default_count = 10
    default_types = ("单项选择题", "填空题")
