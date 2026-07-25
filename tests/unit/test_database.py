from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from edu_exam_agent.infrastructure.database.engine import (
    SCHEMA_VERSION,
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import SchemaVersion


def test_database_initialization_is_idempotent(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "test.db")
    initialize_database(engine)
    initialize_database(engine)
    table_names = set(inspect(engine).get_table_names())
    assert {
        "schema_version",
        "document_profiles",
        "question_fingerprints",
        "question_duplicate_relations",
        "paper_history",
        "paper_history_items",
    } <= table_names
    with Session(engine) as session:
        versions = session.scalars(select(SchemaVersion)).all()
    assert [version.version for version in versions] == [
        "0001",
        "0002",
        "0003",
        "0004",
        "0005",
        SCHEMA_VERSION,
    ]
