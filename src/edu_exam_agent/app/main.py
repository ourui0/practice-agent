"""Desktop application entry point."""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from edu_exam_agent.app.bootstrap import bootstrap
from edu_exam_agent.app.icon import application_icon, configure_windows_app_identity
from edu_exam_agent.ui.theme import apply_light_theme
from edu_exam_agent.ui.windows.main_window import MainWindow


def main(argv: Sequence[str] | None = None) -> int:
    """Start the Qt event loop and show a friendly error on bootstrap failure."""
    arguments = list(argv) if argv is not None else sys.argv
    configure_windows_app_identity()
    application = QApplication(arguments)
    application.setApplicationName("EduExam Agent")
    application.setWindowIcon(application_icon())
    application.setStyle("Fusion")
    application.setFont(QFont("Segoe UI", 10))
    apply_light_theme(application)
    try:
        context = bootstrap()
        window = MainWindow(context)
        window.show()
        return application.exec()
    except Exception as exc:  # top-level crash barrier; details go to logs where available
        logging.getLogger(__name__).exception("应用启动失败")
        QMessageBox.critical(None, "启动失败", f"应用初始化失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
