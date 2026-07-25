"""Material upload, parsing and chapter browsing page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from edu_exam_agent.application.services.course_service import CourseService
from edu_exam_agent.application.services.document_service import DocumentDescriptor, DocumentService
from edu_exam_agent.infrastructure.database.models import DocumentModel
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


class MaterialImportWorker(QObject):
    progress = Signal(str)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, service: DocumentService, course_id: int, filenames: list[str]) -> None:
        super().__init__()
        self._service = service
        self._course_id = course_id
        self._filenames = filenames
        self._cancelled = False

    @Slot()
    def run(self) -> None:
        for filename in self._filenames:
            if self._cancelled:
                break
            path = Path(filename)
            self.progress.emit(f"正在解析：{path.name}")
            try:
                self._service.import_document(self._course_id, path)
            except Exception as exc:
                self.failed.emit(path.name, str(exc))
        self.finished.emit()

    @Slot()
    def cancel(self) -> None:
        self._cancelled = True


class MaterialReparseWorker(QObject):
    failed = Signal(str)
    finished = Signal(bool)

    def __init__(
        self,
        service: DocumentService,
        document_id: int,
        replacement: Path | None,
    ) -> None:
        super().__init__()
        self._service = service
        self._document_id = document_id
        self._replacement = replacement

    @Slot()
    def run(self) -> None:
        try:
            if self._replacement is None:
                self._service.reparse_document(self._document_id)
            else:
                self._service.replace_document(self._document_id, self._replacement)
        except Exception as exc:
            self.failed.emit(str(exc))
            self.finished.emit(False)
            return
        self.finished.emit(True)


class MaterialPage(QWidget):
    def __init__(
        self, courses: CourseService, documents: DocumentService, retriever: FtsRetriever
    ) -> None:
        super().__init__()
        self._course_service = courses
        self._document_service = documents
        self._retriever = retriever
        self._courses = []
        self._documents: list[DocumentModel] = []
        self._descriptors: list[DocumentDescriptor] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 26)
        title = QLabel("教材管理")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("当前课程"))
        self.course = QComboBox()
        self.course.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self.course, 1)
        upload = QPushButton("上传并解析教材")
        upload.clicked.connect(self._upload)
        toolbar.addWidget(upload)
        delete = QPushButton("删除教材")
        delete.clicked.connect(self._delete)
        toolbar.addWidget(delete)
        layout.addLayout(toolbar)

        repair_bar = QHBoxLayout()
        relocate = QPushButton("重新定位文件")
        relocate.clicked.connect(self._relink)
        repair_bar.addWidget(relocate)
        replace = QPushButton("替换并重新解析")
        replace.clicked.connect(self._replace)
        repair_bar.addWidget(replace)
        reparse = QPushButton("重新解析")
        reparse.clicked.connect(self._reparse)
        repair_bar.addWidget(reparse)
        edit_chapter = QPushButton("校正目录项")
        edit_chapter.clicked.connect(self._edit_chapter)
        repair_bar.addWidget(edit_chapter)
        toggle_chapter = QPushButton("启用 / 排除目录项")
        toggle_chapter.clicked.connect(self._toggle_chapter)
        repair_bar.addWidget(toggle_chapter)
        self.show_excluded = QCheckBox("显示历史及已排除目录")
        self.show_excluded.toggled.connect(self._load_chapters)
        repair_bar.addWidget(self.show_excluded)
        repair_bar.addStretch(1)
        layout.addLayout(repair_bar)

        splitter = QSplitter()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ("文件名", "教材信息", "文件状态", "解析状态", "页数", "章节", "文本块")
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._load_chapters)
        self.chapters = QTreeWidget()
        self.chapters.setHeaderLabels(("解析后的章节", "起始页", "状态"))
        splitter.addWidget(self.table)
        splitter.addWidget(self.chapters)
        splitter.setSizes((650, 400))
        layout.addWidget(splitter, 1)
        search_bar = QHBoxLayout()
        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText("输入教材关键词，例如：平行线、一次函数")
        self.search_text.returnPressed.connect(self._search)
        search_bar.addWidget(self.search_text, 1)
        search_button = QPushButton("检索教材原文")
        search_button.clicked.connect(self._search)
        search_bar.addWidget(search_button)
        layout.addLayout(search_bar)
        self.results = QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(("教材", "章节", "页码", "原文摘要"))
        self.results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results.setMaximumHeight(190)
        layout.addWidget(self.results)
        self.status = QLabel("支持 PDF、DOCX、TXT 和 Markdown。")
        layout.addWidget(self.status)
        self.cancel_button = QPushButton("取消解析")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_import)
        layout.addWidget(self.cancel_button)
        self._thread: QThread | None = None
        self._worker: MaterialImportWorker | MaterialReparseWorker | None = None
        self.reload_courses()

    def reload_courses(self) -> None:
        self._courses = self._course_service.list()
        self.course.blockSignals(True)
        self.course.clear()
        for item in self._courses:
            self.course.addItem(item.name, item.id)
        self.course.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        course_id = self.course.currentData()
        self._descriptors = (
            self._document_service.list_descriptors(course_id) if course_id else []
        )
        self._documents = [descriptor.document for descriptor in self._descriptors]
        self.table.setRowCount(len(self._descriptors))
        state_labels = {
            "healthy": "可用",
            "missing": "文件缺失",
            "changed": "文件已变化",
            "incomplete": "索引不完整",
            "parse_failed": "解析失败",
            "pending": "等待解析",
        }
        for row, descriptor in enumerate(self._descriptors):
            document = descriptor.document
            values = (
                document.filename,
                descriptor.identity.display_name,
                state_labels.get(descriptor.health.state, descriptor.health.state),
                document.parse_status,
                str(document.page_count),
                str(document.chapter_count),
                str(document.chunk_count),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(descriptor.health.message)
                if descriptor.health.ready_for_generation:
                    item.setForeground(Qt.GlobalColor.darkGreen)
                elif column == 2:
                    item.setForeground(Qt.GlobalColor.red)
                self.table.setItem(row, column, item)
        self.chapters.clear()
        if not self._courses:
            self.status.setText("请先在课程管理中创建课程。")

    def _upload(self) -> None:
        course_id = self.course.currentData()
        if not course_id:
            QMessageBox.information(self, "缺少课程", "请先创建并选择课程。")
            return
        filenames, _ = QFileDialog.getOpenFileNames(
            self, "选择教材", "", "教材文件 (*.pdf *.docx *.txt *.md *.markdown)"
        )
        if not filenames:
            return
        self._thread = QThread(self)
        self._worker = MaterialImportWorker(self._document_service, course_id, filenames)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.status.setText)
        self._worker.failed.connect(self._show_import_error)
        self._worker.finished.connect(self._import_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self.cancel_button.setEnabled(True)
        self._thread.start()

    @Slot(str, str)
    def _show_import_error(self, filename: str, message: str) -> None:
        QMessageBox.warning(self, "教材导入失败", f"{filename}：{message}")

    @Slot()
    def _import_finished(self) -> None:
        self.status.setText("教材解析任务已结束。")
        self.cancel_button.setEnabled(False)
        self.refresh()
        self._worker = None
        self._thread = None

    def _cancel_import(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("正在取消；当前文件完成后停止。")

    def _selected_document(self) -> DocumentModel | None:
        row = self.table.currentRow()
        return self._documents[row] if 0 <= row < len(self._documents) else None

    def _load_chapters(self) -> None:
        document = self._selected_document()
        self.chapters.clear()
        if document is None:
            return
        for chapter in self._document_service.list_chapters(
            document.id, include_excluded=self.show_excluded.isChecked()
        ):
            item = QTreeWidgetItem(
                self.chapters,
                (
                    chapter.title,
                    str(chapter.page_start),
                    "历史/已排除" if chapter.is_excluded else "使用中",
                ),
            )
            item.setData(0, Qt.ItemDataRole.UserRole, chapter.id)
            if chapter.is_excluded:
                item.setForeground(0, Qt.GlobalColor.gray)

    def _selected_chapter(self):
        selected = self.chapters.currentItem()
        if selected is None:
            return None
        chapter_id = selected.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(chapter_id, int):
            return None
        document = self._selected_document()
        if document is None:
            return None
        return next(
            (
                chapter
                for chapter in self._document_service.list_chapters(
                    document.id, include_excluded=True
                )
                if chapter.id == chapter_id
            ),
            None,
        )

    def _relink(self) -> None:
        document = self._selected_document()
        if document is None:
            QMessageBox.information(self, "请选择教材", "请先选择需要重新定位的教材。")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择原教材的新位置",
            "",
            "教材文件 (*.pdf *.docx *.txt *.md *.markdown)",
        )
        if not filename:
            return
        try:
            self._document_service.relink_document(document.id, Path(filename))
        except ValueError as exc:
            QMessageBox.warning(self, "重新定位失败", str(exc))
            return
        self.status.setText("教材文件已重新定位，原解析和题目来源保持不变。")
        self.refresh()

    def _replace(self) -> None:
        document = self._selected_document()
        if document is None:
            QMessageBox.information(self, "请选择教材", "请先选择需要替换的教材。")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择替换教材",
            "",
            "教材文件 (*.pdf *.docx *.txt *.md *.markdown)",
        )
        if not filename:
            return
        if (
            QMessageBox.question(
                self,
                "确认替换",
                "将使用新文件重新识别目录和文本索引。旧解析会作为历史快照保留，"
                "不会破坏已有题目的教材来源。是否继续？",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._start_reparse(document.id, Path(filename))

    def _reparse(self) -> None:
        document = self._selected_document()
        if document is None:
            QMessageBox.information(self, "请选择教材", "请先选择需要重新解析的教材。")
            return
        try:
            self._document_service.assert_ready_for_generation(document.id)
        except ValueError as exc:
            if "重新定位" in str(exc):
                QMessageBox.warning(self, "无法重新解析", f"{exc}\n请先重新定位文件。")
                return
        self._start_reparse(document.id, None)

    def _start_reparse(self, document_id: int, replacement: Path | None) -> None:
        if self._thread is not None:
            QMessageBox.information(self, "任务进行中", "请等待当前教材任务完成。")
            return
        self._thread = QThread(self)
        worker = MaterialReparseWorker(
            self._document_service, document_id, replacement
        )
        self._worker = worker
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        worker.failed.connect(
            lambda message: QMessageBox.warning(self, "教材解析失败", message)
        )
        worker.finished.connect(self._reparse_finished)
        worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self.status.setText("正在解析教材并重建目录与检索索引……")
        self.cancel_button.setEnabled(False)
        self._thread.start()

    @Slot(bool)
    def _reparse_finished(self, succeeded: bool) -> None:
        self.status.setText(
            "教材解析和索引重建完成。" if succeeded else "教材解析失败，原解析仍然保留。"
        )
        self.refresh()
        self._worker = None
        self._thread = None

    def _edit_chapter(self) -> None:
        chapter = self._selected_chapter()
        if chapter is None:
            QMessageBox.information(self, "请选择目录项", "请先选择需要校正的章节或小节。")
            return
        title, accepted = QInputDialog.getText(
            self, "校正目录名称", "章节或小节名称", text=chapter.title
        )
        if not accepted:
            return
        page_start, accepted = QInputDialog.getInt(
            self,
            "校正起始页",
            "起始页",
            chapter.page_start,
            1,
            10000,
        )
        if not accepted:
            return
        try:
            self._document_service.update_chapter(
                chapter.id, title=title, page_start=page_start
            )
        except ValueError as exc:
            QMessageBox.warning(self, "目录校正失败", str(exc))
            return
        self.status.setText("目录项已校正，章节选择器和检索索引已同步更新。")
        self._load_chapters()

    def _toggle_chapter(self) -> None:
        chapter = self._selected_chapter()
        if chapter is None:
            QMessageBox.information(self, "请选择目录项", "请先选择需要启用或排除的目录项。")
            return
        try:
            self._document_service.set_chapter_excluded(
                chapter.id, not chapter.is_excluded
            )
        except ValueError as exc:
            QMessageBox.warning(self, "目录调整失败", str(exc))
            return
        self.status.setText("目录使用状态已更新。")
        self.refresh()

    def _delete(self) -> None:
        document = self._selected_document()
        if (
            document
            and QMessageBox.question(
                self, "确认删除", f"确定删除教材“{document.filename}”及其解析索引吗？"
            )
            == QMessageBox.StandardButton.Yes
        ):
            self._document_service.delete(document.id)
            self.refresh()

    def _search(self) -> None:
        course_id = self.course.currentData()
        if not course_id:
            return
        try:
            matches = self._retriever.search(self.search_text.text(), course_id)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.results.setRowCount(len(matches))
        for row, match in enumerate(matches):
            page = (
                str(match.page_start)
                if match.page_start == match.page_end
                else f"{match.page_start}-{match.page_end}"
            )
            values = (match.document_name, match.chapter_title, page, match.excerpt)
            for column, value in enumerate(values):
                self.results.setItem(row, column, QTableWidgetItem(value))
        self.status.setText(f"找到 {len(matches)} 条教材依据。")
