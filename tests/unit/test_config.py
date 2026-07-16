from __future__ import annotations

from pathlib import Path

from edu_exam_agent.app.config import load_config


def test_load_config_creates_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config, paths = load_config(config_file)
    assert config.app.name == "EduExam Agent"
    assert paths.data_dir == tmp_path
    assert paths.database_file.name == "edu_exam_agent.db"
    assert config_file.exists()
