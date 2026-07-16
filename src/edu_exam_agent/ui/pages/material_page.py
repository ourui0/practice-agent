"""Material upload, parsing and chapter browsing page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
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
from edu_exam_agent.application.services.document_service import DocumentService
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 26)
        title = QLabel("教材管理")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
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

        splitter = QSplitter()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(("文件名", "格式", "状态", "页数", "章节", "文本块"))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._load_chapters)
        self.chapters = QTreeWidget()
        self.chapters.setHeaderLabels(("解析后的章节", "起始页"))
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
        self._worker: MaterialImportWorker | None = None
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
        self._documents = self._document_service.list(course_id) if course_id else []
        self.table.setRowCount(len(self._documents))
        for row, document in enumerate(self._documents):
            values = (
                document.filename,
                document.file_type,
                document.parse_status,
                str(document.page_count),
                str(document.chapter_count),
                str(document.chunk_count),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
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
        for chapter in self._document_service.list_chapters(document.id):
            QTreeWidgetItem(self.chapters, (chapter.title, str(chapter.page_start)))

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
