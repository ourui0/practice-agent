from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from edu_exam_agent.app.bootstrap import bootstrap
from edu_exam_agent.ui.windows.main_window import MainWindow


def test_application_bootstrap_and_window(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    context = bootstrap(tmp_path / "config.toml")
    window = MainWindow(context)
    assert application.applicationName() is not None
    assert window.windowTitle() == "EduExam Agent"
    assert context.paths.database_file.exists()
    window.close()
