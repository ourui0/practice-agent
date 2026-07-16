"""Application configuration loading and user data path resolution."""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AppSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "EduExam Agent"
    language: str = "zh_CN"
    theme: str = "system"


class StorageSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_dir: str = ""


class LoggingSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"
    max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    backup_count: int = Field(default=5, ge=1, le=20)


class DatabaseSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = "edu_exam_agent.db"


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: AppSection = AppSection()
    storage: StorageSection = StorageSection()
    logging: LoggingSection = LoggingSection()
    database: DatabaseSection = DatabaseSection()


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    data_dir: Path
    config_file: Path
    database_file: Path
    log_dir: Path


def default_data_dir() -> Path:
    """Return the per-user writable data directory on Windows and other platforms."""
    base = os.getenv("APPDATA")
    if base:
        return Path(base) / "EduExamAgent"
    return Path.home() / ".edu_exam_agent"


def load_config(config_file: Path | None = None) -> tuple[AppConfig, RuntimePaths]:
    """Load validated TOML configuration and resolve runtime paths."""
    initial_dir = config_file.parent if config_file else default_data_dir()
    initial_dir.mkdir(parents=True, exist_ok=True)
    target = config_file or initial_dir / "config.toml"
    if not target.exists():
        example = Path.cwd() / "config.example.toml"
        if example.exists():
            shutil.copyfile(example, target)
        else:
            target.write_text("", encoding="utf-8")

    with target.open("rb") as stream:
        raw: dict[str, Any] = tomllib.load(stream)
    config = AppConfig.model_validate(raw)
    data_dir = (
        Path(config.storage.data_dir).expanduser() if config.storage.data_dir else initial_dir
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    paths = RuntimePaths(
        data_dir=data_dir,
        config_file=target,
        database_file=data_dir / config.database.filename,
        log_dir=data_dir / "logs",
    )
    return config, paths
