"""Shared application icon and Windows taskbar identity."""

from __future__ import annotations

import ctypes
import sys
from functools import lru_cache
from importlib.resources import files

from PySide6.QtGui import QIcon

APP_USER_MODEL_ID = "EduExamAgent.Desktop"
APP_ICON_RESOURCE = "assets/app_icon.png"
APP_WINDOWS_ICON_RESOURCE = "assets/app_icon.ico"


@lru_cache(maxsize=1)
def application_icon() -> QIcon:
    """Load the packaged application icon for every Qt top-level window."""
    resource = files("edu_exam_agent").joinpath(APP_ICON_RESOURCE)
    return QIcon(str(resource))


def configure_windows_app_identity() -> None:
    """Prevent Windows from grouping the app under the generic Python icon."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            APP_USER_MODEL_ID
        )
    except (AttributeError, OSError):
        return
