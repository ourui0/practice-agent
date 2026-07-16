"""LLM provider configuration and connectivity checks."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from edu_exam_agent.infrastructure.database.models import (
    LLMProviderAuditModel,
    LLMProviderConfigModel,
)
from edu_exam_agent.infrastructure.llm import OpenAICompatibleProvider
from edu_exam_agent.infrastructure.security import SecretStore


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    provider_name: str
    base_url: str
    model_name: str
    has_api_key: bool


class ProviderService:
    def __init__(self, engine: Engine, secrets: SecretStore) -> None:
        self._engine = engine
        self._secrets = secrets

    def get_default(self) -> ProviderConfig | None:
        with Session(self._engine) as session:
            row = session.scalar(
                select(LLMProviderConfigModel).where(LLMProviderConfigModel.is_default.is_(True))
            )
            if row is None:
                return None
            return ProviderConfig(
                row.provider_name,
                row.base_url,
                row.model_name,
                self._secrets.has(row.api_key_reference),
            )

    def save(self, provider_name: str, base_url: str, model_name: str, api_key: str) -> None:
        if (
            not provider_name.strip()
            or not base_url.startswith("https://")
            or not model_name.strip()
        ):
            raise ValueError("请填写有效的服务名称、HTTPS 地址和模型名称")
        reference = f"provider:{provider_name.strip().lower()}"
        if api_key:
            self._secrets.set(reference, api_key.strip())
        elif not self._secrets.has(reference):
            raise ValueError("API Key 不能为空")
        with Session(self._engine) as session:
            row = session.scalar(
                select(LLMProviderConfigModel).where(
                    LLMProviderConfigModel.provider_name == provider_name.strip()
                )
            )
            if row is None:
                row = LLMProviderConfigModel(
                    provider_name=provider_name.strip(),
                    base_url=base_url.rstrip("/"),
                    model_name=model_name.strip(),
                    api_key_reference=reference,
                    is_default=True,
                )
                session.add(row)
            else:
                row.base_url = base_url.rstrip("/")
                row.model_name = model_name.strip()
                row.api_key_reference = reference
                row.is_default = True
            session.commit()
        self._audit(provider_name.strip(), model_name.strip(), "保存配置", True, "配置已安全保存")

    def test_connection(self) -> list[str]:
        config = self.get_default()
        if config is None:
            raise ValueError("请先保存模型配置")
        reference = f"provider:{config.provider_name.lower()}"
        key = self._secrets.get(reference)
        if not key:
            raise ValueError("未找到安全存储的 API Key")
        request = urllib.request.Request(
            f"{config.base_url}/models", headers={"Authorization": f"Bearer {key}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            models = [item["id"] for item in payload.get("data", []) if "id" in item]
            self._audit(config.provider_name, config.model_name, "连接测试", True, "连接成功")
            return models
        except Exception as exc:
            self._audit(config.provider_name, config.model_name, "连接测试", False, str(exc)[:300])
            raise

    def create_provider(self) -> tuple[OpenAICompatibleProvider, str]:
        config = self.get_default()
        if config is None:
            raise ValueError("请先在模型设置中保存配置")
        key = self._secrets.get(f"provider:{config.provider_name.lower()}")
        if not key:
            raise ValueError("请先在模型设置中保存 API Key")
        return OpenAICompatibleProvider(config.base_url, config.model_name, key), config.model_name

    def list_audits(self, limit: int = 50) -> list[LLMProviderAuditModel]:
        with Session(self._engine) as session:
            statement = (
                select(LLMProviderAuditModel)
                .order_by(
                    LLMProviderAuditModel.created_at.desc(),
                    LLMProviderAuditModel.id.desc(),
                )
                .limit(limit)
            )
            return list(session.scalars(statement))

    def _audit(self, provider: str, model: str, action: str, succeeded: bool, message: str) -> None:
        with Session(self._engine) as session:
            session.add(
                LLMProviderAuditModel(
                    provider_name=provider,
                    model_name=model,
                    action=action,
                    succeeded=succeeded,
                    message=message,
                )
            )
            session.commit()
