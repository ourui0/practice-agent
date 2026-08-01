"""Course management page with persistent CRUD operations."""

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

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.infrastructure.database.models import CourseModel
from edu_exam_agent.ui.theme import PAGE_MARGINS
from edu_exam_agent.ui.widgets import EmptyStateWidget, StatusLabel


class CourseDialog(QDialog):
    def __init__(self, course: CourseModel | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑课程" if course else "新建课程")
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        self.name = QLineEdit(course.name if course else "")
        self.subject = QLineEdit(course.subject if course else "")
        self.stage = QComboBox()
        self.stage.addItems(("", "小学", "初中", "高中", "高校", "职业教育", "其他"))
        self.grade = QLineEdit(course.grade if course else "")
        self.semester = QLineEdit(course.semester if course else "")
        self.version = QLineEdit(course.textbook_version if course else "")
        self.duration = QSpinBox()
        self.duration.setRange(1, 600)
        self.duration.setValue(course.default_duration_minutes if course else 90)
        self.score = QSpinBox()
        self.score.setRange(1, 1000)
        self.score.setValue(course.default_total_score if course else 100)
        self.difficulty = QSpinBox()
        self.difficulty.setRange(1, 5)
        self.difficulty.setValue(course.default_difficulty if course else 3)
        self.description = QTextEdit(course.description if course else "")
        self.description.setMaximumHeight(90)
        if course and course.education_stage:
            index = self.stage.findText(course.education_stage)
            if index >= 0:
                self.stage.setCurrentIndex(index)
        for label, widget in (
            ("课程名称*", self.name),
            ("学科", self.subject),
            ("教学阶段", self.stage),
            ("年级", self.grade),
            ("学期", self.semester),
            ("教材版本", self.version),
            ("默认时长（分钟）", self.duration),
            ("默认总分", self.score),
            ("默认难度（1-5）", self.difficulty),
            ("课程说明", self.description),
        ):
            form.addRow(label, widget)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "输入有误", "课程名称不能为空。")
            return
        self.accept()

    def value(self) -> CourseInput:
        return CourseInput(
            name=self.name.text().strip(),
            subject=self.subject.text().strip(),
            education_stage=self.stage.currentText(),
            grade=self.grade.text().strip(),
            semester=self.semester.text().strip(),
            textbook_version=self.version.text().strip(),
            description=self.description.toPlainText().strip(),
            default_duration_minutes=self.duration.value(),
            default_total_score=self.score.value(),
            default_difficulty=self.difficulty.value(),
        )


class CoursePage(QWidget):
    def __init__(self, service: CourseService) -> None:
        super().__init__()
        self._service = service
        self._courses: list[CourseModel] = []
        layout = QVBoxLayout(self)
        left, top, right, bottom = PAGE_MARGINS
        layout.setContentsMargins(left, top, right, bottom)
        title = QLabel("课程管理")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        toolbar = QHBoxLayout()
        self.create_btn = QPushButton("新建课程")
        self.create_btn.clicked.connect(self._create)
        toolbar.addWidget(self.create_btn)
        self.edit_btn = QPushButton("编辑")
        self.edit_btn.clicked.connect(self._edit)
        toolbar.addWidget(self.edit_btn)
        self.duplicate_btn = QPushButton("复制")
        self.duplicate_btn.clicked.connect(self._duplicate)
        toolbar.addWidget(self.duplicate_btn)
        self.archive_btn = QPushButton("归档/恢复")
        self.archive_btn.clicked.connect(self._archive)
        toolbar.addWidget(self.archive_btn)
        self.delete_btn = QPushButton("删除")
        self.delete_btn.clicked.connect(self._delete)
        toolbar.addWidget(self.delete_btn)
        self.show_archived = QCheckBox("显示已归档")
        self.show_archived.toggled.connect(self.refresh)
        toolbar.addWidget(self.show_archived)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ("课程名称", "学科", "阶段", "年级", "学期", "总分", "状态")
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)
        self.table.itemSelectionChanged.connect(self._update_button_states)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # Enter key = edit
        enter_shortcut = QShortcut(QKeySequence("Return"), self.table)
        enter_shortcut.activated.connect(self._edit)
        layout.addWidget(self.table)
        self.empty_state = EmptyStateWidget(
            icon="📋",
            message="还没有课程，创建第一个课程开始使用",
            action_label="新建课程",
        )
        self.empty_state.action_button.clicked.connect(self._create)
        self.empty_state.hide()
        layout.addWidget(self.empty_state)
        self.status_label = StatusLabel()
        layout.addWidget(self.status_label)
        self._update_button_states()
        self.refresh()

    def refresh(self) -> None:
        self._courses = self._service.list(self.show_archived.isChecked())
        self.table.setRowCount(len(self._courses))
        for row, course in enumerate(self._courses):
            values = (
                course.name,
                course.subject,
                course.education_stage,
                course.grade,
                course.semester,
                str(course.default_total_score),
                "已归档" if course.is_archived else "使用中",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        has_data = len(self._courses) > 0
        self.table.setVisible(has_data)
        self.empty_state.setVisible(not has_data)
        self._update_button_states()

    def _update_button_states(self) -> None:
        has_selection = self.table.currentRow() >= 0
        self.edit_btn.setEnabled(has_selection)
        self.duplicate_btn.setEnabled(has_selection)
        self.archive_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)

    def _selected(self) -> CourseModel | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self._courses[row]

    def _context_menu(self, pos) -> None:
        course = self._selected()
        if course is None:
            return
        menu = QMenu(self)
        menu.addAction("编辑", self._edit)
        menu.addAction("复制", self._duplicate)
        menu.addAction("归档/恢复", self._archive)
        menu.addSeparator()
        menu.addAction("删除", self._delete)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _create(self) -> None:
        dialog = CourseDialog(parent=self)
        if dialog.exec():
            self._service.create(dialog.value())
            self.refresh()

    def _edit(self) -> None:
        course = self._selected()
        if course:
            dialog = CourseDialog(course, self)
            if dialog.exec():
                self._service.update(course.id, dialog.value())
                self.refresh()

    def _duplicate(self) -> None:
        course = self._selected()
        if course:
            self._service.duplicate(course.id)
            self.refresh()

    def _archive(self) -> None:
        course = self._selected()
        if course:
            self._service.set_archived(course.id, not course.is_archived)
            self.refresh()

    def _delete(self) -> None:
        course = self._selected()
        if (
            course
            and QMessageBox.question(self, "确认删除", f"确定删除课程“{course.name}”吗？")
            == QMessageBox.StandardButton.Yes
        ):
            self._service.delete(course.id)
            self.refresh()
