from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from edu_exam_agent.app.bootstrap import bootstrap
from edu_exam_agent.app.icon import application_icon
from edu_exam_agent.ui.windows.main_window import MainWindow


def test_application_bootstrap_and_window(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    context = bootstrap(tmp_path / "config.toml")
    window = MainWindow(context)
    assert application.applicationName() is not None
    assert window.windowTitle() == "EduExam Agent"
    assert not application_icon().isNull()
    assert not window.windowIcon().isNull()
    assert window.windowIcon().cacheKey() == application_icon().cacheKey()
    assert context.paths.database_file.exists()
    window.close()
