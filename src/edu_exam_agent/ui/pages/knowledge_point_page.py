"""Teacher review page for extracted knowledge points."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from edu_exam_agent.application.services.course_service import CourseService
from edu_exam_agent.application.services.knowledge_point_service import (
    KnowledgePointInput,
    KnowledgePointService,
)
from edu_exam_agent.infrastructure.database.models import KnowledgePointModel
from edu_exam_agent.ui.theme import PAGE_MARGINS
from edu_exam_agent.ui.widgets import EmptyStateWidget, StatusLabel


class KnowledgePointDialog(QDialog):
    def __init__(self, point: KnowledgePointModel | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑知识点" if point else "手动添加知识点")
        form = QFormLayout(self)
        self.name = QLineEdit(point.name if point else "")
        self.description = QTextEdit(point.description if point else "")
        self.importance = QSpinBox()
        self.importance.setRange(1, 5)
        self.importance.setValue(point.importance if point else 3)
        self.difficulty = QSpinBox()
        self.difficulty.setRange(1, 5)
        self.difficulty.setValue(point.recommended_difficulty if point else 3)
        self.types = QLineEdit(point.recommended_question_types if point else "选择题、填空题")
        self.note = QTextEdit(point.teacher_note if point else "")
        self.enabled = QCheckBox("启用")
        self.enabled.setChecked(point.is_enabled if point else True)
        form.addRow("知识点名称*", self.name)
        form.addRow("说明", self.description)
        form.addRow("重要程度", self.importance)
        form.addRow("推荐难度", self.difficulty)
        form.addRow("推荐题型", self.types)
        form.addRow("教师备注", self.note)
        form.addRow("状态", self.enabled)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def value(self) -> KnowledgePointInput:
        return KnowledgePointInput(
            name=self.name.text(),
            description=self.description.toPlainText(),
            importance=self.importance.value(),
            recommended_difficulty=self.difficulty.value(),
            recommended_question_types=self.types.text(),
            teacher_note=self.note.toPlainText(),
            is_enabled=self.enabled.isChecked(),
        )


class KnowledgePointPage(QWidget):
    def __init__(self, courses: CourseService, points: KnowledgePointService) -> None:
        super().__init__()
        self._courses_service = courses
        self._service = points
        self._points: list[KnowledgePointModel] = []
        layout = QVBoxLayout(self)
        left, top, right, bottom = PAGE_MARGINS
        layout.setContentsMargins(left, top, right, bottom)
        title = QLabel("知识点管理")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("课程"))
        self.course = QComboBox()
        self.course.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self.course, 1)
        self.extract_btn = QPushButton("从教材提取知识点")
        self.extract_btn.clicked.connect(self._extract)
        toolbar.addWidget(self.extract_btn)
        self.confirm_all_btn = QPushButton("确认全部候选")
        self.confirm_all_btn.clicked.connect(self._confirm_all)
        toolbar.addWidget(self.confirm_all_btn)
        self.create_btn = QPushButton("手动添加")
        self.create_btn.clicked.connect(self._create)
        toolbar.addWidget(self.create_btn)
        self.edit_btn = QPushButton("编辑并确认")
        self.edit_btn.clicked.connect(self._edit)
        toolbar.addWidget(self.edit_btn)
        self.confirm_btn = QPushButton("确认选中")
        self.confirm_btn.clicked.connect(self._confirm)
        toolbar.addWidget(self.confirm_btn)
        self.delete_btn = QPushButton("删除")
        self.delete_btn.clicked.connect(self._delete)
        toolbar.addWidget(self.delete_btn)
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ("知识点", "状态", "来源", "页码", "重要度", "难度", "推荐题型")
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_button_states)
        self.table.doubleClicked.connect(self._edit)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        enter_shortcut = QShortcut(QKeySequence("Return"), self.table)
        enter_shortcut.activated.connect(self._edit)
        layout.addWidget(self.table)
        self.empty_state = EmptyStateWidget(
            icon="🏷",
            message="还没有知识点，从教材中自动提取或手动添加",
            action_label="从教材提取知识点",
        )
        self.empty_state.action_button.clicked.connect(self._extract)
        self.empty_state.hide()
        layout.addWidget(self.empty_state)
        self.status_label = StatusLabel()
        layout.addWidget(self.status_label)
        self._update_button_states()
        self.reload_courses()

    def reload_courses(self) -> None:
        current = self.course.currentData()
        courses = self._courses_service.list()
        self.course.blockSignals(True)
        self.course.clear()
        for course in courses:
            self.course.addItem(course.name, course.id)
        index = self.course.findData(current)
        if index >= 0:
            self.course.setCurrentIndex(index)
        self.course.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        course_id = self.course.currentData()
        self._points = self._service.list(course_id) if course_id else []
        self.table.setRowCount(len(self._points))
        for row, point in enumerate(self._points):
            values = (
                point.name,
                "待确认" if point.status == "candidate" else "已确认",
                "自动提取" if point.source == "automatic" else "教师创建",
                str(point.source_page or ""),
                str(point.importance),
                str(point.recommended_difficulty),
                point.recommended_question_types,
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        has_data = len(self._points) > 0
        self.table.setVisible(has_data)
        self.empty_state.setVisible(not has_data)
        self._update_button_states()

    def _update_button_states(self) -> None:
        has_selection = self.table.currentRow() >= 0
        self.edit_btn.setEnabled(has_selection)
        self.confirm_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)

    def _selected(self) -> KnowledgePointModel | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self._points[row] if row >= 0 else None

    def _context_menu(self, pos) -> None:
        point = self._selected()
        if point is None:
            return
        menu = QMenu(self)
        menu.addAction("编辑并确认", self._edit)
        if point.status != "confirmed":
            menu.addAction("确认选中", self._confirm)
        menu.addSeparator()
        menu.addAction("删除", self._delete)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _extract(self) -> None:
        course_id = self.course.currentData()
        if course_id:
            count = self._service.extract_candidates(course_id)
            self.refresh()
            self.status_label.setText(f"新增 {count} 条有效知识点，已可直接用于生成题目。")

    def _create(self) -> None:
        dialog = KnowledgePointDialog(parent=self)
        if dialog.exec():
            self._service.create_manual(self.course.currentData(), dialog.value())
            self.refresh()

    def _confirm_all(self) -> None:
        course_id = self.course.currentData()
        if course_id:
            count = self._service.confirm_all_candidates(course_id)
            self.refresh()
            self.status_label.setText(f"已确认 {count} 条有效候选知识点，可用于单题生成。")

    def _edit(self) -> None:
        point = self._selected()
        if point:
            dialog = KnowledgePointDialog(point, self)
            if dialog.exec():
                self._service.update(point.id, dialog.value())
                self.refresh()

    def _confirm(self) -> None:
        point = self._selected()
        if point:
            self._service.confirm(point.id)
            self.refresh()

    def _delete(self) -> None:
        point = self._selected()
        if (
            point
            and QMessageBox.question(self, "确认删除", f"确定删除“{point.name}”吗？")
            == QMessageBox.StandardButton.Yes
        ):
            self._service.delete(point.id)
            self.refresh()
