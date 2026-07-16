"""Central logging configuration with rotating files."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from edu_exam_agent.app.config import LoggingSection


def configure_logging(settings: LoggingSection, log_dir: Path) -> Path:
    """Configure console and rotating application log handlers."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "application.log"
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.max_bytes,
        backupCount=settings.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, settings.level.upper(), logging.INFO))
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return log_file
