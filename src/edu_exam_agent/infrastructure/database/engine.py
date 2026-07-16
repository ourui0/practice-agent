"""SQLite engine creation and initial schema setup."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, select, text
from sqlalchemy.orm import Session

from edu_exam_agent.infrastructure.database.models import Base, SchemaVersion

SCHEMA_VERSION = "0004"


def create_database_engine(database_file: Path) -> Engine:
    """Create a SQLite engine with foreign-key enforcement enabled."""
    database_file.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database_file.as_posix()}", future=True)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def initialize_database(engine: Engine) -> None:
    """Create the current schema and retain an ordered local upgrade history."""
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
                chunk_id UNINDEXED, course_id UNINDEXED, document_id UNINDEXED,
                chapter_id UNINDEXED, content, tokenize='trigram'
                )"""
            )
        )
    with Session(engine) as session:
        applied = set(session.scalars(select(SchemaVersion.version)))
        # Version 0001 is the original bootstrap schema. Version 0002 adds
        # courses, documents, chapters and chunks. create_all performs the
        # additive table creation; future column changes must use migrations.
        for version in ("0001", "0002", "0003", SCHEMA_VERSION):
            if version not in applied:
                session.add(SchemaVersion(version=version))
        session.commit()
