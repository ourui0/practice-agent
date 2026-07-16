"""Persistent question bank management page."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
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
from edu_exam_agent.application.services.question_bank_service import (
    QuestionBankService,
    QuestionEdit,
)
from edu_exam_agent.infrastructure.database.models import QuestionModel


class QuestionEditDialog(QDialog):
    def __init__(self, question: QuestionModel, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑题目")
        self.resize(650, 520)
        form = QFormLayout(self)
        self.stem = QTextEdit(question.stem)
        self.answer = QTextEdit(question.answer)
        self.analysis = QTextEdit(question.analysis)
        self.score = QSpinBox()
        self.score.setRange(1, 100)
        self.score.setValue(question.score)
        self.difficulty = QSpinBox()
        self.difficulty.setRange(1, 5)
        self.difficulty.setValue(question.difficulty)
        form.addRow("题干", self.stem)
        form.addRow("答案", self.answer)
        form.addRow("解析", self.analysis)
        form.addRow("分值", self.score)
        form.addRow("难度", self.difficulty)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def value(self) -> QuestionEdit:
        return QuestionEdit(
            self.stem.toPlainText(),
            self.answer.toPlainText(),
            self.analysis.toPlainText(),
            self.score.value(),
            self.difficulty.value(),
        )


class QuestionBankPage(QWidget):
    def __init__(self, courses: CourseService, bank: QuestionBankService) -> None:
        super().__init__()
        self._courses = courses
        self._bank = bank
        self._questions = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 24, 30, 24)
        title = QLabel("题库")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(title)
        filters = QHBoxLayout()
        self.course = QComboBox()
        self.course.currentIndexChanged.connect(self.refresh)
        self.keyword = QLineEdit()
        self.keyword.setPlaceholderText("搜索题干或解析")
        self.keyword.returnPressed.connect(self.refresh)
        self.question_type = QComboBox()
        self.question_type.addItems(
            (
                "全部题型",
                "单项选择题",
                "多项选择题",
                "判断题",
                "填空题",
                "简答题",
                "计算题",
                "应用题",
            )
        )
        self.question_type.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.course)
        filters.addWidget(self.keyword, 1)
        filters.addWidget(self.question_type)
        search = QPushButton("筛选")
        search.clicked.connect(self.refresh)
        filters.addWidget(search)
        layout.addLayout(filters)
        actions = QHBoxLayout()
        for text, slot in (
            ("查看详情", self._view),
            ("编辑", self._edit),
            ("复制", self._duplicate),
            ("历史版本", self._history),
            ("删除", self._delete),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ("编号", "题型", "题干", "难度", "质量", "推荐分", "状态")
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        self.reload_courses()

    def reload_courses(self) -> None:
        current = self.course.currentData()
        self.course.blockSignals(True)
        self.course.clear()
        self.course.addItem("全部课程", None)
        for course in self._courses.list():
            self.course.addItem(course.name, course.id)
        index = self.course.findData(current)
        if index >= 0:
            self.course.setCurrentIndex(index)
        self.course.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        qtype = "" if self.question_type.currentIndex() <= 0 else self.question_type.currentText()
        self._questions = self._bank.list(self.course.currentData(), self.keyword.text(), qtype)
        self.table.setRowCount(len(self._questions))
        for row, question in enumerate(self._questions):
            values = (
                str(question.id),
                question.question_type,
                question.stem,
                str(question.difficulty),
                f"{question.quality_score:.0%}",
                str(question.recommendation_score),
                question.status,
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

    def _selected(self) -> QuestionModel | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "请选择题目", "请先选择一道题目。")
        return self._questions[row] if row >= 0 else None

    def _edit(self) -> None:
        question = self._selected()
        if question:
            dialog = QuestionEditDialog(question, self)
            if dialog.exec():
                self._bank.update(question.id, dialog.value())
                self.refresh()

    def _view(self) -> None:
        question = self._selected()
        if question is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"题目 {question.id}")
        dialog.resize(720, 620)
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(
            f"题干：{question.stem}\n\n答案：{question.answer}\n\n解析：{question.analysis}"
        )
        layout.addWidget(text, 1)
        detail = self._bank.score_detail(question.id)
        if detail is not None:
            dimensions = json.loads(detail.dimensions_json)
            score_text = "　".join(f"{name} {value:g}" for name, value in dimensions.items())
            score_label = QLabel(
                f"综合质量：{detail.total_points:g} 分\n{score_text}\n"
                f"计算负荷：{detail.calculation_load}/10　融合知识点：{detail.fusion_count}　"
                f"推理层次：{detail.reasoning_steps}　难点特征：{detail.hard_point_count}　"
                f"估计难度：{detail.estimated_difficulty}"
            )
            score_label.setWordWrap(True)
            layout.addWidget(score_label)
        figure = self._bank.figure(question.id)
        if figure is not None:
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = QPixmap()
            pixmap.loadFromData(figure.png_data, "PNG")
            label.setPixmap(
                pixmap.scaled(
                    620,
                    320,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            layout.addWidget(label)
        close = QPushButton("关闭")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def _duplicate(self) -> None:
        question = self._selected()
        if question:
            self._bank.duplicate(question.id)
            self.refresh()

    def _history(self) -> None:
        question = self._selected()
        if question:
            versions = self._bank.versions(question.id)
            detail = (
                "\n".join(
                    f"{v.created_at:%Y-%m-%d %H:%M:%S}：{', '.join(json.loads(v.changed_fields))}"
                    for v in versions
                )
                or "暂无历史版本"
            )
            QMessageBox.information(self, "题目历史版本", detail)

    def _delete(self) -> None:
        question = self._selected()
        if (
            question
            and QMessageBox.question(self, "确认删除", "确定删除选中题目吗？")
            == QMessageBox.StandardButton.Yes
        ):
            self._bank.delete(question.id)
            self.refresh()
