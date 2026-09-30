"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from app.api.middleware import RequestContextMiddleware
from app.api.routes import integration_router, router
from app.container import AppContainer
from app.core.config import MerchantCatalog
from tools.registry import ToolAdapterRegistry


def create_app(
    database_path: Path | None = None,
    *,
    merchant_catalog: MerchantCatalog | None = None,
    tool_adapters: ToolAdapterRegistry | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Retail Customer Agent API",
        version="0.4.0",
        description="可配置零售客服 Agent 框架 API。",
    )
    app.state.container = AppContainer.build(
        database_path=database_path,
        merchant_catalog=merchant_catalog,
        tool_adapters=tool_adapters,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(router)
    app.include_router(integration_router)
    return app


app = create_app()
