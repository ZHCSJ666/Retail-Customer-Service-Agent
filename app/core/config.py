"""Runtime and merchant configuration loading.

Merchant files are deliberately data-only. Future skills receive an already-loaded
merchant configuration rather than importing a merchant's JSON fixtures directly.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RefundRulesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    unshipped_order_eligible: bool
    delivered_return_window_days: int = Field(ge=0, le=365)
    cancelled_order_eligible: bool


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tool_steps: int = Field(ge=1, le=12)
    max_history_messages: int = Field(ge=0, le=30)


class DemoRequirementsConfig(BaseModel):
    """Per-merchant fixture minimums; secondary examples may be intentionally small."""

    model_config = ConfigDict(extra="forbid")

    min_products: int = Field(ge=1)
    min_customers: int = Field(ge=1)
    min_orders: int = Field(ge=1)
    min_knowledge_documents: int = Field(ge=1)
    min_failure_scenarios: int = Field(ge=0)
    required_order_statuses: list[str] = Field(min_length=1)


class MerchantConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1)
    demo_disclaimer: str = Field(min_length=1)
    order_id_pattern: str = Field(min_length=3, max_length=200)
    knowledge_dir: str = Field(min_length=1)
    prompt_path: str = Field(min_length=1)
    enabled_skills: list[str] = Field(min_length=1)
    agent: AgentConfig
    tool_adapters: dict[str, str]
    mock_data: dict[str, str]
    refund_rules: RefundRulesConfig
    demo_requirements: DemoRequirementsConfig

    @field_validator("order_id_pattern")
    @classmethod
    def validate_order_id_pattern(cls, value: str) -> str:
        try:
            expression = re.compile(value)
        except re.error as exc:
            raise ValueError("order_id_pattern must be a valid regular expression") from exc
        if expression.search("") is not None:
            raise ValueError("order_id_pattern must not match an empty string")
        return value

    @field_validator("tool_adapters")
    @classmethod
    def validate_tool_adapters(cls, value: dict[str, str]) -> dict[str, str]:
        required = {"product", "order", "shipping", "handoff"}
        if set(value) != required:
            raise ValueError(f"tool_adapters must contain exactly: {sorted(required)}")
        if any(not adapter_id.strip() for adapter_id in value.values()):
            raise ValueError("tool_adapters values must not be empty")
        return value


@dataclass(frozen=True)
class LoadedMerchant:
    """A validated merchant config and its source file."""

    config: MerchantConfig
    source_path: Path

    def resolve_project_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def knowledge_dir(self) -> Path:
        return self.resolve_project_path(self.config.knowledge_dir)

    @property
    def prompt_path(self) -> Path:
        return self.resolve_project_path(self.config.prompt_path)

    def mock_data_path(self, dataset: str) -> Path:
        try:
            return self.resolve_project_path(self.config.mock_data[dataset])
        except KeyError as exc:
            raise KeyError(f"Merchant '{self.config.merchant_id}' has no '{dataset}' fixture") from exc


class MerchantCatalog:
    """Loads every merchant YAML below configs/merchants exactly once at startup."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or PROJECT_ROOT / "configs" / "merchants"
        self._merchants = self._load_all()

    def _load_all(self) -> dict[str, LoadedMerchant]:
        config_files = sorted(self.config_dir.glob("*.yaml"))
        if not config_files:
            raise RuntimeError(f"No merchant configuration found in {self.config_dir}")

        merchants: dict[str, LoadedMerchant] = {}
        for path in config_files:
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                config = MerchantConfig.model_validate(raw)
            except (OSError, yaml.YAMLError, ValidationError) as exc:
                raise RuntimeError(f"Invalid merchant configuration: {path}") from exc
            if config.merchant_id in merchants:
                raise RuntimeError(f"Duplicate merchant_id '{config.merchant_id}'")
            merchants[config.merchant_id] = LoadedMerchant(config=config, source_path=path)
        return merchants

    def get(self, merchant_id: str) -> LoadedMerchant:
        try:
            return self._merchants[merchant_id]
        except KeyError as exc:
            raise KeyError(f"Unknown merchant '{merchant_id}'") from exc

    def all(self) -> list[LoadedMerchant]:
        return list(self._merchants.values())

    def upsert_runtime_config(self, config: MerchantConfig) -> LoadedMerchant:
        """Apply a previously validated revision without importing executable code."""
        loaded = LoadedMerchant(
            config=config,
            source_path=PROJECT_ROOT / "data" / "runtime_config_revisions" / f"{config.merchant_id}.json",
        )
        self._merchants[config.merchant_id] = loaded
        return loaded


@dataclass(frozen=True)
class RuntimeSettings:
    """Settings that are intentionally read only from environment variables."""

    llm_mode: Literal["mock", "openai_compatible"]
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str | None
    llm_timeout_seconds: float
    llm_max_retries: int
    framework_auth_mode: Literal["disabled", "api_key"]
    integration_principals: tuple["IntegrationPrincipalConfig", ...]

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        # `.env` is a local convenience file only; real environment variables
        # retain precedence and neither values nor keys are exposed by the API.
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        mode = os.getenv("LLM_MODE", "mock").strip().lower()
        if mode not in {"mock", "openai_compatible"}:
            raise RuntimeError("LLM_MODE must be 'mock' or 'openai_compatible'")

        auth_mode = os.getenv("FRAMEWORK_AUTH_MODE", "disabled").strip().lower()
        if auth_mode not in {"disabled", "api_key"}:
            raise RuntimeError("FRAMEWORK_AUTH_MODE must be 'disabled' or 'api_key'")
        principals = _load_integration_principals(os.getenv("FRAMEWORK_API_KEYS_JSON", ""))
        if auth_mode == "api_key" and not principals:
            raise RuntimeError("FRAMEWORK_API_KEYS_JSON must contain at least one principal in api_key mode")

        try:
            timeout = float(os.getenv("LLM_TIMEOUT", "30"))
            retries = int(os.getenv("LLM_MAX_RETRIES", "2"))
        except ValueError as exc:
            raise RuntimeError("LLM_TIMEOUT and LLM_MAX_RETRIES must be numeric") from exc
        if timeout <= 0 or retries < 0:
            raise RuntimeError("LLM_TIMEOUT must be positive and LLM_MAX_RETRIES must be non-negative")

        return cls(
            llm_mode=mode,
            llm_base_url=os.getenv("LLM_BASE_URL") or None,
            llm_api_key=os.getenv("LLM_API_KEY") or None,
            llm_model=os.getenv("LLM_MODEL") or None,
            llm_timeout_seconds=timeout,
            llm_max_retries=retries,
            framework_auth_mode=auth_mode,
            integration_principals=principals,
        )


@dataclass(frozen=True)
class IntegrationPrincipalConfig:
    """A host-to-framework API credential; values must never be returned by HTTP APIs."""

    principal_id: str
    api_key: str
    merchant_ids: tuple[str, ...]


def _load_integration_principals(raw_value: str) -> tuple[IntegrationPrincipalConfig, ...]:
    if not raw_value.strip():
        return ()
    try:
        raw_principals = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("FRAMEWORK_API_KEYS_JSON must be a JSON array") from exc
    if not isinstance(raw_principals, list):
        raise RuntimeError("FRAMEWORK_API_KEYS_JSON must be a JSON array")

    principals: list[IntegrationPrincipalConfig] = []
    seen_principal_ids: set[str] = set()
    seen_api_keys: set[str] = set()
    for raw_principal in raw_principals:
        if not isinstance(raw_principal, dict) or set(raw_principal) != {
            "principal_id",
            "api_key",
            "merchant_ids",
        }:
            raise RuntimeError(
                "Each integration principal must contain principal_id, api_key, and merchant_ids"
            )
        principal_id = raw_principal["principal_id"]
        api_key = raw_principal["api_key"]
        merchant_ids = raw_principal["merchant_ids"]
        if not isinstance(principal_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", principal_id):
            raise RuntimeError("Integration principal_id must use lowercase letters, numbers, underscores, or hyphens")
        if not isinstance(api_key, str) or len(api_key.strip()) < 16:
            raise RuntimeError("Integration API keys must contain at least 16 characters")
        if (
            not isinstance(merchant_ids, list)
            or not merchant_ids
            or any(not isinstance(merchant_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", merchant_id) for merchant_id in merchant_ids)
        ):
            raise RuntimeError("Integration merchant_ids must be a non-empty list of merchant IDs")
        if principal_id in seen_principal_ids or api_key in seen_api_keys:
            raise RuntimeError("Integration principal IDs and API keys must be unique")
        seen_principal_ids.add(principal_id)
        seen_api_keys.add(api_key)
        principals.append(
            IntegrationPrincipalConfig(
                principal_id=principal_id,
                api_key=api_key,
                merchant_ids=tuple(dict.fromkeys(merchant_ids)),
            )
        )
    return tuple(principals)
