"""Application dependency container for the single-process MVP."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.model_adapter import StructuredIntentModel, build_intent_model
from agent.orchestrator import AgentOrchestrator
from app.core.config import LoadedMerchant, MerchantCatalog, MerchantConfig, RuntimeSettings
from app.core.database import SessionStore
from app.core.framework_store import FrameworkStore
from app.core.webhooks import WebhookDispatcher
from app.demo_data.repository import DemoDataRepository
from rag.ingest import ingest_merchant_knowledge
from rag.retrieve import LocalRetriever
from rag.store import SQLiteRagStore
from skills.registry import SkillRegistry, build_core_registry
from tools.registry import ToolAdapterRegistry, build_default_tool_adapter_registry


@dataclass
class AppContainer:
    settings: RuntimeSettings
    merchants: MerchantCatalog
    demo_data: DemoDataRepository
    sessions: SessionStore
    framework_store: FrameworkStore
    webhooks: WebhookDispatcher
    rag_store: SQLiteRagStore
    retriever: LocalRetriever
    intent_model: StructuredIntentModel
    skills: SkillRegistry
    tool_adapters: ToolAdapterRegistry
    agent: AgentOrchestrator

    @classmethod
    def build(
        cls,
        database_path: Path | None = None,
        *,
        merchant_catalog: MerchantCatalog | None = None,
        tool_adapters: ToolAdapterRegistry | None = None,
    ) -> "AppContainer":
        merchants = merchant_catalog or MerchantCatalog()
        adapter_registry = tool_adapters or build_default_tool_adapter_registry()
        for merchant in merchants.all():
            missing, unsupported = adapter_registry.validate_merchant(merchant)
            if missing or unsupported:
                raise RuntimeError(
                    f"Merchant '{merchant.config.merchant_id}' selects unavailable adapters: "
                    f"missing={missing}, unsupported={unsupported}"
                )
        settings = RuntimeSettings.from_environment()
        demo_data = DemoDataRepository(merchants)
        sessions = SessionStore(database_path or Path("data") / "retail_customer_agent.db")
        framework_store = FrameworkStore(sessions.database_path)
        webhooks = WebhookDispatcher(framework_store)
        for revision in framework_store.active_config_revisions():
            config = MerchantConfig.model_validate(revision["config"])
            missing, unsupported = adapter_registry.validate_merchant(
                LoadedMerchant(config=config, source_path=Path("<stored-revision>"))
            )
            if missing or unsupported:
                raise RuntimeError(f"Active merchant revision has unavailable adapters: {config.merchant_id}")
            merchants.upsert_runtime_config(config)
        rag_store = SQLiteRagStore(sessions.database_path)
        for merchant in merchants.all():
            ingest_merchant_knowledge(merchant, rag_store)
        retriever = LocalRetriever(rag_store)
        intent_model = build_intent_model(settings)
        skills = build_core_registry()
        agent = AgentOrchestrator(
            sessions=sessions,
            merchants=merchants,
            demo_data=demo_data,
            retriever=retriever,
            intent_model=intent_model,
            registry=skills,
            tool_adapters=adapter_registry,
        )
        return cls(
            settings=settings,
            merchants=merchants,
            demo_data=demo_data,
            sessions=sessions,
            framework_store=framework_store,
            webhooks=webhooks,
            rag_store=rag_store,
            retriever=retriever,
            intent_model=intent_model,
            skills=skills,
            tool_adapters=adapter_registry,
            agent=agent,
        )
