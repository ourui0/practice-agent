"""Teacher review page for extracted knowledge points."""

from __future__ import annotations

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
        layout.setContentsMargins(32, 26, 32, 26)
        title = QLabel("知识点管理")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("课程"))
        self.course = QComboBox()
        self.course.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self.course, 1)
        for text, slot in (
            ("从教材提取知识点", self._extract),
            ("确认全部候选", self._confirm_all),
            ("手动添加", self._create),
            ("编辑并确认", self._edit),
            ("确认选中", self._confirm),
            ("删除", self._delete),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ("知识点", "状态", "来源", "页码", "重要度", "难度", "推荐题型")
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        self.status = QLabel()
        layout.addWidget(self.status)
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

    def _selected(self) -> KnowledgePointModel | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "请选择知识点", "请先选择一条知识点。")
        return self._points[row] if row >= 0 else None

    def _extract(self) -> None:
        course_id = self.course.currentData()
        if course_id:
            count = self._service.extract_candidates(course_id)
            self.refresh()
            self.status.setText(f"新增 {count} 条有效知识点，已可直接用于生成题目。")

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
            self.status.setText(f"已确认 {count} 条有效候选知识点，可用于单题生成。")

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
