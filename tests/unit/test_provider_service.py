from __future__ import annotations

from edu_exam_agent.application.services.provider_service import ProviderService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.security import SecretStore


def test_save_provider_creates_audit_without_secret(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "provider.db")
    initialize_database(engine)
    secrets = SecretStore(tmp_path / "secrets.dat")
    service = ProviderService(engine, secrets)
    service.save("DeepSeek", "https://api.deepseek.com", "deepseek-v4-pro", "secret-value")

    config = service.get_default()
    assert config is not None and config.has_api_key
    assert config.model_name == "deepseek-v4-pro"
    audits = service.list_audits()
    assert len(audits) == 1
    assert audits[0].action == "保存配置"
    assert "secret-value" not in audits[0].message
