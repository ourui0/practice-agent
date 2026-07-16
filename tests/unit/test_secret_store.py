from __future__ import annotations

from edu_exam_agent.infrastructure.security import SecretStore


def test_dpapi_secret_round_trip(tmp_path) -> None:
    store = SecretStore(tmp_path / "secrets.dat")
    store.set("provider:test", "test-secret-value")
    assert store.has("provider:test")
    assert store.get("provider:test") == "test-secret-value"
    assert "test-secret-value" not in (tmp_path / "secrets.dat").read_text(encoding="utf-8")
