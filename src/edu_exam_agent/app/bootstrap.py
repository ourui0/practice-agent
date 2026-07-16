"""Composition root for application infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from edu_exam_agent.app.config import AppConfig, RuntimePaths, load_config
from edu_exam_agent.app.logging_config import configure_logging
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)


@dataclass(frozen=True, slots=True)
class ApplicationContext:
    config: AppConfig
    paths: RuntimePaths
    engine: Engine
    log_file: Path


def bootstrap(config_file: Path | None = None) -> ApplicationContext:
    """Initialize configuration, logging and database in a deterministic order."""
    config, paths = load_config(config_file)
    log_file = configure_logging(config.logging, paths.log_dir)
    engine = create_database_engine(paths.database_file)
    initialize_database(engine)
    return ApplicationContext(config=config, paths=paths, engine=engine, log_file=log_file)
