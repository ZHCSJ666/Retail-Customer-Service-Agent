"""Explicit registry for host-supplied business tool adapters.

Adapter code is registered by the embedding Python application, never imported
from a merchant YAML value. Configuration data can only select a known adapter
ID and therefore cannot become executable code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.core.config import LoadedMerchant
from app.core.database import SessionStore
from app.demo_data.repository import DemoDataRepository
from tools.protocols import MerchantToolSet, TOOL_KINDS, ToolKind


@dataclass(frozen=True)
class AdapterBuildContext:
    """Trusted dependencies made available to a registered adapter factory."""

    merchant: LoadedMerchant
    demo_data: DemoDataRepository
    sessions: SessionStore


AdapterFactory = Callable[[AdapterBuildContext], object]


@dataclass(frozen=True)
class ToolAdapterDefinition:
    tool_kind: ToolKind
    adapter_id: str
    description: str
    factory: AdapterFactory


class ToolAdapterRegistry:
    """Maps stable adapter IDs to host-registered factories by tool kind."""

    def __init__(self) -> None:
        self._definitions: dict[tuple[ToolKind, str], ToolAdapterDefinition] = {}

    def register(
        self,
        *,
        tool_kind: ToolKind,
        adapter_id: str,
        description: str,
        factory: AdapterFactory,
    ) -> None:
        clean_id = adapter_id.strip()
        if tool_kind not in TOOL_KINDS:
            raise ValueError(f"Unsupported tool kind: {tool_kind}")
        if not clean_id or not clean_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError("adapter_id must contain only letters, numbers, underscores, or hyphens")
        if not description.strip():
            raise ValueError("Adapter description must not be empty")
        if not callable(factory):
            raise TypeError("Adapter factory must be callable")
        key = (tool_kind, clean_id)
        if key in self._definitions:
            raise RuntimeError(f"Duplicate {tool_kind} adapter registration: {clean_id}")
        self._definitions[key] = ToolAdapterDefinition(
            tool_kind=tool_kind,
            adapter_id=clean_id,
            description=description.strip(),
            factory=factory,
        )

    def supports(self, *, tool_kind: ToolKind, adapter_id: str) -> bool:
        return (tool_kind, adapter_id) in self._definitions

    def capabilities(self) -> list[dict[str, str]]:
        return [
            {
                "tool_kind": definition.tool_kind,
                "adapter_id": definition.adapter_id,
                "description": definition.description,
            }
            for definition in sorted(
                self._definitions.values(), key=lambda item: (item.tool_kind, item.adapter_id)
            )
        ]

    def validate_merchant(self, merchant: LoadedMerchant) -> tuple[list[str], dict[str, str]]:
        configured = merchant.config.tool_adapters
        missing = [kind for kind in TOOL_KINDS if not configured.get(kind)]
        unsupported = {
            kind: configured[kind]
            for kind in TOOL_KINDS
            if configured.get(kind) and not self.supports(tool_kind=kind, adapter_id=configured[kind])
        }
        return missing, unsupported

    def build_toolset(
        self,
        *,
        merchant: LoadedMerchant,
        demo_data: DemoDataRepository,
        sessions: SessionStore,
    ) -> MerchantToolSet:
        missing, unsupported = self.validate_merchant(merchant)
        if missing or unsupported:
            raise RuntimeError(
                "Merchant adapter configuration is not registered: "
                f"missing={missing}, unsupported={unsupported}"
            )
        context = AdapterBuildContext(merchant=merchant, demo_data=demo_data, sessions=sessions)
        adapters: dict[str, object] = {}
        for kind in TOOL_KINDS:
            adapter_id = merchant.config.tool_adapters[kind]
            adapter = self._definitions[(kind, adapter_id)].factory(context)
            _validate_adapter_shape(tool_kind=kind, adapter=adapter)
            adapters[kind] = adapter
        return MerchantToolSet(
            product=adapters["product"],  # type: ignore[arg-type]
            order=adapters["order"],  # type: ignore[arg-type]
            shipping=adapters["shipping"],  # type: ignore[arg-type]
            handoff=adapters["handoff"],  # type: ignore[arg-type]
        )


def build_default_tool_adapter_registry() -> ToolAdapterRegistry:
    """Build the local Demo registry; host applications may add adapters."""
    # Imported lazily to keep this registry independent of concrete adapters.
    from tools.mock import register_fixture_mock_adapters

    registry = ToolAdapterRegistry()
    register_fixture_mock_adapters(registry)
    return registry


def _validate_adapter_shape(*, tool_kind: ToolKind, adapter: object) -> None:
    required_method = {
        "product": "get_product",
        "order": "lookup_for_customer",
        "shipping": "lookup_for_authorized_order",
        "handoff": "create_ticket",
    }[tool_kind]
    if not callable(getattr(adapter, required_method, None)):
        raise TypeError(f"Registered {tool_kind} adapter does not implement {required_method}()")
