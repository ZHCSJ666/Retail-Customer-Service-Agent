"""Stable, merchant-agnostic business tool contracts.

Skills depend on these interfaces. They never import JSON fixtures or choose a
customer identity from a message, so a future HTTP implementation can replace a
Mock adapter without changing Skill logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolFailure(RuntimeError):
    code = "TOOL_ERROR"
    safe_message = "业务查询暂时不可用。"


class ToolTimeout(ToolFailure):
    code = "TOOL_TIMEOUT"
    safe_message = "业务查询超时，请稍后重试。"


class OrderLookupStatus(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"


class OrderLineItem(ToolModel):
    product_id: str
    product_name: str
    quantity: int = Field(ge=1)


class CustomerOrder(ToolModel):
    """An already-authorized order. It intentionally contains no customer ID."""

    order_id: str
    status: str
    created_at: str
    delivered_at: str | None = None
    items: tuple[OrderLineItem, ...]
    total_cents: int = Field(ge=0)
    shipping_payload: dict[str, object] | None = None


class OrderLookupToolResult(ToolModel):
    status: OrderLookupStatus
    order: CustomerOrder | None = None


class ShippingInfo(ToolModel):
    availability: str
    carrier: str | None = None
    tracking_number: str | None = None
    status: str | None = None
    estimated_delivery_at: str | None = None


class ProductRecord(ToolModel):
    product_id: str
    name: str
    description: str
    price_cents: int = Field(ge=0)
    stock: int = Field(ge=0)
    attributes: dict[str, object]


class HandoffTicket(ToolModel):
    ticket_id: str
    status: str
    created_at: str


class OrderTool(Protocol):
    def lookup_for_customer(self, *, customer_id: str, order_id: str) -> OrderLookupToolResult: ...


class ShippingTool(Protocol):
    def lookup_for_authorized_order(self, *, order: CustomerOrder) -> ShippingInfo: ...


class ProductTool(Protocol):
    def get_product(self, *, product_id: str) -> ProductRecord | None: ...


class HandoffTool(Protocol):
    def create_ticket(self, *, session_id: str, summary: str, reason: str) -> HandoffTicket: ...


ToolKind = Literal["product", "order", "shipping", "handoff"]
TOOL_KINDS: tuple[ToolKind, ...] = ("product", "order", "shipping", "handoff")


@dataclass(frozen=True)
class MerchantToolSet:
    """A complete set of merchant adapters consumed by Skills.

    Fields use stable Protocols rather than concrete mock classes, so host
    applications can replace adapters without changing Skill implementations.
    """

    product: ProductTool
    order: OrderTool
    shipping: ShippingTool
    handoff: HandoffTool
