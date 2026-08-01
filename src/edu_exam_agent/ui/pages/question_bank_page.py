"""Persistent question bank management page."""

from __future__ import annotations

import json

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
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
from edu_exam_agent.application.services.question_bank_service import (
    QuestionBankService,
    QuestionEdit,
)
from edu_exam_agent.infrastructure.database.models import QuestionModel
from edu_exam_agent.ui.theme import PAGE_MARGINS
from edu_exam_agent.ui.widgets import EmptyStateWidget, StatusLabel


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
        self._questions: list = []
        layout = QVBoxLayout(self)
        left, top, right, bottom = PAGE_MARGINS
        layout.setContentsMargins(left, top, right, bottom)
        title = QLabel("题库")
        title.setObjectName("pageTitle")
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
        self.view_btn = QPushButton("查看详情")
        self.view_btn.clicked.connect(self._view)
        actions.addWidget(self.view_btn)
        self.edit_btn = QPushButton("编辑")
        self.edit_btn.clicked.connect(self._edit)
        actions.addWidget(self.edit_btn)
        self.duplicate_btn = QPushButton("复制")
        self.duplicate_btn.clicked.connect(self._duplicate)
        actions.addWidget(self.duplicate_btn)
        self.approve_btn = QPushButton("保留为可用变式")
        self.approve_btn.clicked.connect(self._approve_variant)
        actions.addWidget(self.approve_btn)
        self.history_btn = QPushButton("历史版本")
        self.history_btn.clicked.connect(self._history)
        actions.addWidget(self.history_btn)
        self.delete_btn = QPushButton("删除")
        self.delete_btn.clicked.connect(self._delete)
        actions.addWidget(self.delete_btn)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ("编号", "题型", "题干", "难度", "质量", "推荐分", "状态")
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_button_states)
        self.table.doubleClicked.connect(self._view)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        enter_shortcut = QShortcut(QKeySequence("Return"), self.table)
        enter_shortcut.activated.connect(self._view)
        layout.addWidget(self.table)
        self.empty_state = EmptyStateWidget(
            icon="📝",
            message="题库为空，生成第一道题目",
            action_label="去生成题目 →",
        )
        # Wire empty-state button to navigate (handled via parent window)
        self.empty_state.action_button.clicked.connect(self._navigate_to_single_question)
        self.empty_state.hide()
        layout.addWidget(self.empty_state)
        self.status_label = StatusLabel()
        layout.addWidget(self.status_label)
        self._update_button_states()
        self.reload_courses()

    def _navigate_to_single_question(self) -> None:
        window = self.window()
        if hasattr(window, "_select_page"):
            # Find "single" page index and switch
            page_keys = getattr(window, "_page_keys", [])
            for i, key in enumerate(page_keys):
                if key == "single":
                    window._select_page(i)
                    return

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
            stem_text = question.stem
            stem_display = stem_text[:60] + "…" if len(stem_text) > 60 else stem_text
            values = (
                str(question.id),
                question.question_type,
                stem_display,
                str(question.difficulty),
                f"{question.quality_score:.0%}",
                str(question.recommendation_score),
                question.status,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 2 and len(stem_text) > 60:
                    item.setToolTip(stem_text)
                self.table.setItem(row, column, item)
        has_data = len(self._questions) > 0
        self.table.setVisible(has_data)
        self.empty_state.setVisible(not has_data)
        self.status_label.setText(
            f"共 {len(self._questions)} 道题"
            if self._questions else ""
        )
        self._update_button_states()

    def focus_question_ids(self, question_ids: list[int]) -> None:
        """Show and select questions created by a chat-agent task."""
        wanted = {int(question_id) for question_id in question_ids}
        self.course.setCurrentIndex(0)
        self.question_type.setCurrentIndex(0)
        self.keyword.clear()
        self.refresh()
        self.table.clearSelection()
        first_row = -1
        for row, question in enumerate(self._questions):
            if question.id not in wanted:
                continue
            index = self.table.model().index(row, 0)
            self.table.selectionModel().select(
                index,
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            if first_row < 0:
                first_row = row
        if first_row >= 0:
            self.table.selectionModel().setCurrentIndex(
                self.table.model().index(first_row, 0),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
            self.table.scrollToItem(self.table.item(first_row, 0))
            self.status_label.setText(f"已定位本次生成的 {len(wanted)} 道题")

    def _update_button_states(self) -> None:
        has_selection = self.table.currentRow() >= 0
        self.view_btn.setEnabled(has_selection)
        self.edit_btn.setEnabled(has_selection)
        self.duplicate_btn.setEnabled(has_selection)
        self.approve_btn.setEnabled(has_selection)
        self.history_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)

    def _selected(self) -> QuestionModel | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self._questions[row] if row >= 0 else None

    def _context_menu(self, pos) -> None:
        question = self._selected()
        if question is None:
            return
        menu = QMenu(self)
        menu.addAction("查看详情", self._view)
        menu.addAction("编辑", self._edit)
        menu.addAction("复制", self._duplicate)
        menu.addAction("保留为可用变式", self._approve_variant)
        menu.addSeparator()
        menu.addAction("删除", self._delete)
        menu.exec(self.table.viewport().mapToGlobal(pos))

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
        fingerprint = self._bank.fingerprint_detail(question.id)
        if fingerprint is not None:
            tags = json.loads(fingerprint.model_tags_json)
            reasons = json.loads(fingerprint.difficulty_reasons_json)
            difficulty_label = QLabel(
                f"难度校准：教师请求 {fingerprint.requested_difficulty} 档 → "
                f"系统判定 {fingerprint.calibrated_difficulty} 档\n"
                f"母题标签：{'、'.join(tags) if tags else '未识别到固定母题'}\n"
                f"判定依据：{'；'.join(reasons)}"
            )
            difficulty_label.setWordWrap(True)
            layout.addWidget(difficulty_label)
        matches = self._bank.duplicate_matches(question.id, 3)
        if matches:
            level_names = {
                "duplicate": "重复",
                "high": "高度相似",
                "warning": "相似提示",
                "none": "低相似",
            }
            lines = ["重复检测（最接近的3题）："]
            for match in matches:
                breakdown = match.breakdown
                lines.append(
                    f"题目 {match.question_id}｜{level_names[breakdown.level]}｜"
                    f"总相似度 {breakdown.total:.0%}｜文本 {breakdown.text:.0%}｜"
                    f"数学结构 {breakdown.math:.0%}｜母题 {breakdown.model:.0%}\n"
                    f"共同标签：{'、'.join(match.shared_model_tags) or '无'}\n"
                    f"{match.stem[:100]}"
                )
            duplicate_label = QLabel("\n\n".join(lines))
            duplicate_label.setWordWrap(True)
            duplicate_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(duplicate_label)
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

    def _approve_variant(self) -> None:
        question = self._selected()
        if question is None:
            return
        if (
            QMessageBox.question(
                self,
                "确认保留变式",
                "该操作会允许此题进入自动组卷。请确认它具有独立教学价值，而不是仅替换数字。",
            )
            == QMessageBox.StandardButton.Yes
        ):
            self._bank.approve_variant(question.id)
            self.refresh()

    def _delete(self) -> None:
        question = self._selected()
        if (
            question
            and QMessageBox.question(self, "确认删除", "确定删除选中题目吗？")
            == QMessageBox.StandardButton.Yes
        ):
            self._bank.delete(question.id)
            self.refresh()
