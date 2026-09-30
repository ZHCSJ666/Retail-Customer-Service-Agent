"""Mock merchant adapters backed by the configured DemoDataRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from app.core.config import LoadedMerchant
from app.core.database import SessionStore
from app.demo_data.repository import DemoDataRepository
from tools.protocols import (
    CustomerOrder,
    HandoffTicket,
    MerchantToolSet,
    OrderLineItem,
    OrderLookupStatus,
    OrderLookupToolResult,
    ProductRecord,
    ShippingInfo,
    ToolFailure,
    ToolTimeout,
)

if TYPE_CHECKING:
    from tools.registry import AdapterBuildContext, ToolAdapterRegistry


FaultMode = Literal["timeout", "error"] | None


class MockOrderTool:
    def __init__(
        self, repository: DemoDataRepository, merchant_id: str, fault_mode: FaultMode = None
    ) -> None:
        self.repository = repository
        self.merchant_id = merchant_id
        self.fault_mode = fault_mode

    def lookup_for_customer(self, *, customer_id: str, order_id: str) -> OrderLookupToolResult:
        _raise_for_fault(self.fault_mode)
        raw_order = self.repository.order_by_id(self.merchant_id, order_id)
        if raw_order is None:
            return OrderLookupToolResult(status=OrderLookupStatus.NOT_FOUND)
        if raw_order.get("customer_id") != customer_id:
            # Do not place an order object or owner identifier in this response.
            return OrderLookupToolResult(status=OrderLookupStatus.FORBIDDEN)

        items: list[OrderLineItem] = []
        for raw_item in raw_order.get("items", []):
            product_id = str(raw_item["product_id"])
            product = self.repository.product_by_id(self.merchant_id, product_id)
            if product is None:
                raise ToolFailure("Order fixture references a missing product")
            items.append(
                OrderLineItem(
                    product_id=product_id,
                    product_name=str(product["name"]),
                    quantity=int(raw_item["quantity"]),
                )
            )

        return OrderLookupToolResult(
            status=OrderLookupStatus.FOUND,
            order=CustomerOrder(
                order_id=str(raw_order["order_id"]),
                status=str(raw_order["status"]),
                created_at=str(raw_order["created_at"]),
                delivered_at=str(raw_order["delivered_at"]) if raw_order.get("delivered_at") else None,
                items=tuple(items),
                total_cents=int(raw_order["total_cents"]),
                shipping_payload=raw_order.get("shipping"),
            ),
        )


class MockShippingTool:
    def __init__(self, fault_mode: FaultMode = None) -> None:
        self.fault_mode = fault_mode

    def lookup_for_authorized_order(self, *, order: CustomerOrder) -> ShippingInfo:
        _raise_for_fault(self.fault_mode)
        if order.shipping_payload is None:
            return ShippingInfo(availability="not_shipped")
        payload = order.shipping_payload
        status = str(payload.get("status", ""))
        if status == "物流信息暂缺":
            return ShippingInfo(availability="unknown", status=status)
        return ShippingInfo(
            availability="available",
            carrier=str(payload["carrier"]),
            tracking_number=str(payload["tracking_number"]),
            status=status,
            estimated_delivery_at=(
                str(payload["estimated_delivery_at"]) if payload.get("estimated_delivery_at") else None
            ),
        )


class MockProductTool:
    def __init__(
        self, repository: DemoDataRepository, merchant_id: str, fault_mode: FaultMode = None
    ) -> None:
        self.repository = repository
        self.merchant_id = merchant_id
        self.fault_mode = fault_mode

    def get_product(self, *, product_id: str) -> ProductRecord | None:
        _raise_for_fault(self.fault_mode)
        product = self.repository.product_by_id(self.merchant_id, product_id)
        if product is None:
            return None
        return ProductRecord(
            product_id=str(product["product_id"]),
            name=str(product["name"]),
            description=str(product["description"]),
            price_cents=int(product["price_cents"]),
            stock=int(product["stock"]),
            attributes=dict(product["attributes"]),
        )


class MockHandoffTool:
    """Creates a local ticket only; it never contacts a real support channel."""

    def __init__(self, sessions: SessionStore, merchant_id: str, fault_mode: FaultMode = None) -> None:
        self.sessions = sessions
        self.merchant_id = merchant_id
        self.fault_mode = fault_mode

    def create_ticket(self, *, session_id: str, summary: str, reason: str) -> HandoffTicket:
        _raise_for_fault(self.fault_mode)
        ticket_id = f"MOCK-TKT-{uuid4().hex[:10].upper()}"
        record = self.sessions.create_handoff_ticket(
            ticket_id=ticket_id,
            session_id=session_id,
            merchant_id=self.merchant_id,
            summary=summary,
            reason=reason,
        )
        return HandoffTicket(
            ticket_id=record["ticket_id"], status=record["status"], created_at=record["created_at"]
        )


def _raise_for_fault(fault_mode: FaultMode) -> None:
    if fault_mode == "timeout":
        raise ToolTimeout("Mock tool timeout")
    if fault_mode == "error":
        raise ToolFailure("Mock tool error")


def build_mock_toolset(
    merchant: LoadedMerchant, repository: DemoDataRepository, sessions: SessionStore
) -> MerchantToolSet:
    """Compatibility helper for local callers; the Agent uses ToolAdapterRegistry."""
    from tools.registry import build_default_tool_adapter_registry

    return build_default_tool_adapter_registry().build_toolset(
        merchant=merchant, demo_data=repository, sessions=sessions
    )


def register_fixture_mock_adapters(registry: "ToolAdapterRegistry") -> None:
    """Register both local fixture aliases for every stable Tool Protocol."""
    for adapter_id in ("mock", "fixture_mock"):
        registry.register(
            tool_kind="product",
            adapter_id=adapter_id,
            description="本地商品 fixture 适配器。",
            factory=_build_mock_product,
        )
        registry.register(
            tool_kind="order",
            adapter_id=adapter_id,
            description="本地订单 fixture 适配器，包含归属校验。",
            factory=_build_mock_order,
        )
        registry.register(
            tool_kind="shipping",
            adapter_id=adapter_id,
            description="本地物流 fixture 适配器。",
            factory=_build_mock_shipping,
        )
        registry.register(
            tool_kind="handoff",
            adapter_id=adapter_id,
            description="本地模拟人工工单适配器。",
            factory=_build_mock_handoff,
        )


def _build_mock_product(context: "AdapterBuildContext") -> MockProductTool:
    return MockProductTool(context.demo_data, context.merchant.config.merchant_id)


def _build_mock_order(context: "AdapterBuildContext") -> MockOrderTool:
    return MockOrderTool(context.demo_data, context.merchant.config.merchant_id)


def _build_mock_shipping(context: "AdapterBuildContext") -> MockShippingTool:
    del context
    return MockShippingTool()


def _build_mock_handoff(context: "AdapterBuildContext") -> MockHandoffTool:
    return MockHandoffTool(context.sessions, context.merchant.config.merchant_id)
