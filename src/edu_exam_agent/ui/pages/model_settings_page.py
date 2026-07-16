"""Easy model provider configuration page."""

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from edu_exam_agent.application.services.provider_service import ProviderService


class ConnectionTestWorker(QObject):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, service: ProviderService) -> None:
        super().__init__()
        self._service = service

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(self._service.test_connection())
        except Exception as exc:
            self.failed.emit(str(exc))


class ModelSettingsPage(QWidget):
    def __init__(self, service: ProviderService) -> None:
        super().__init__()
        self._service = service
        self._test_thread = None
        self._test_worker = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 28)
        title = QLabel("模型设置")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(title)
        hint = QLabel("API Key 使用 Windows DPAPI 加密，只能由当前 Windows 用户解密。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        box = QGroupBox("OpenAI 兼容服务")
        form = QFormLayout(box)
        self.provider = QLineEdit("DeepSeek")
        self.base_url = QLineEdit("https://api.deepseek.com")
        self.model = QLineEdit("deepseek-v4-pro")
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("输入 API Key；已保存时可留空")
        form.addRow("服务名称", self.provider)
        form.addRow("服务地址", self.base_url)
        form.addRow("模型名称", self.model)
        form.addRow("API Key", self.api_key)
        layout.addWidget(box)
        save = QPushButton("安全保存配置")
        save.clicked.connect(self._save)
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(self._test)
        layout.addWidget(save)
        layout.addWidget(self.test_button)
        self.status = QLabel()
        layout.addWidget(self.status)
        history_label = QLabel("安全操作记录（不包含 API Key）")
        history_label.setStyleSheet("font-weight: 600; margin-top: 12px;")
        layout.addWidget(history_label)
        self.history = QTableWidget(0, 5)
        self.history.setHorizontalHeaderLabels(("时间", "操作", "服务", "模型", "结果"))
        self.history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.history, 1)
        self.reload()

    def reload(self) -> None:
        config = self._service.get_default()
        if config:
            self.provider.setText(config.provider_name)
            self.base_url.setText(config.base_url)
            self.model.setText(config.model_name)
            message = "API Key 已安全保存。" if config.has_api_key else "尚未保存 API Key。"
            self.status.setText(message)
        self._reload_history()

    def _save(self) -> None:
        try:
            self._service.save(
                self.provider.text(), self.base_url.text(), self.model.text(), self.api_key.text()
            )
            self.api_key.clear()
            self.status.setText("配置已保存，API Key 已加密。")
            self._reload_history()
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))

    def _test(self) -> None:
        self.test_button.setEnabled(False)
        self.status.setText("正在后台测试连接，界面仍可继续使用……")
        self._test_thread = QThread(self)
        self._test_worker = ConnectionTestWorker(self._service)
        self._test_worker.moveToThread(self._test_thread)
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.succeeded.connect(self._test_succeeded)
        self._test_worker.failed.connect(self._test_failed)
        self._test_worker.succeeded.connect(self._test_thread.quit)
        self._test_worker.failed.connect(self._test_thread.quit)
        self._test_thread.finished.connect(self._test_worker.deleteLater)
        self._test_thread.finished.connect(self._test_thread.deleteLater)
        self._test_thread.start()

    @Slot(list)
    def _test_succeeded(self, models: list[str]) -> None:
        message = (
            "连接成功，目标模型可用。"
            if self.model.text() in models
            else "连接成功，但模型列表中未找到目标模型。"
        )
        self.status.setText(message)
        self.test_button.setEnabled(True)
        self._reload_history()

    @Slot(str)
    def _test_failed(self, message: str) -> None:
        self.test_button.setEnabled(True)
        QMessageBox.warning(self, "连接失败", message)
        self._reload_history()

    def _reload_history(self) -> None:
        records = self._service.list_audits()
        self.history.setRowCount(len(records))
        for row, record in enumerate(records):
            values = (
                record.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                record.action,
                record.provider_name,
                record.model_name,
                "成功" if record.succeeded else f"失败：{record.message}",
            )
            for column, value in enumerate(values):
                self.history.setItem(row, column, QTableWidgetItem(value))
