"""Public API data contracts for the Phase 1 service."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictModel):
    status: Literal["ok"]
    service: str
    database_ready: bool
    llm_mode: Literal["mock", "openai_compatible"]


class SessionCreateRequest(StrictModel):
    merchant_id: str = Field(default="star_select", pattern=r"^[a-z][a-z0-9_]*$")
    customer_id: str = Field(min_length=1, max_length=64)


class SessionResponse(StrictModel):
    session_id: str
    merchant_id: str
    customer_id: str
    created_at: str
    updated_at: str


class MessageResponse(StrictModel):
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: str


class SessionDetailResponse(SessionResponse):
    messages: list[MessageResponse]


class CustomerResponse(StrictModel):
    customer_id: str
    display_name: str


class MerchantResponse(StrictModel):
    merchant_id: str
    display_name: str
    demo_disclaimer: str


class AdapterCapabilityResponse(StrictModel):
    tool_kind: Literal["product", "order", "shipping", "handoff"]
    adapter_id: str
    description: str


class MerchantCapabilityResponse(StrictModel):
    merchant_id: str
    display_name: str
    enabled_skills: list[str]
    order_id_pattern: str
    tool_adapters: dict[str, str]


class FrameworkManifestResponse(StrictModel):
    api_version: Literal["v1"]
    authentication_mode: Literal["disabled", "api_key"]
    chat_endpoints: list[str]
    extension_points: list[str]
    identity_boundary: str
    adapter_capabilities: list[AdapterCapabilityResponse]


class MerchantConfigValidationRequest(StrictModel):
    """JSON representation of the same contract used by merchant YAML files."""

    merchant_config: dict[str, Any]


class MerchantConfigValidationResponse(StrictModel):
    valid: bool
    merchant_id: str
    enabled_skills: list[str]
    unknown_skill_ids: list[str]
    missing_tool_adapters: list[str]
    unsupported_tool_adapters: dict[str, str]


class AuditEventResponse(StrictModel):
    request_id: str
    principal_id: str
    merchant_id: str | None
    action: str
    outcome: str
    metadata: dict[str, Any]
    created_at: str


class MetricCountResponse(StrictModel):
    action: str
    outcome: str
    count: int


class FrameworkEventResponse(StrictModel):
    event_id: str
    merchant_id: str
    event_type: str
    request_id: str
    payload: dict[str, Any]
    delivery_status: Literal["pending", "delivered", "not_configured", "failed"]
    delivery_attempts: int = Field(ge=0)
    last_error: str | None = None
    created_at: str
    delivered_at: str | None = None


class ConfigRevisionResponse(StrictModel):
    revision_id: str
    merchant_id: str
    version: int = Field(ge=1)
    status: Literal["draft", "active", "superseded"]
    config: dict[str, Any]
    created_by: str
    created_at: str
    activated_at: str | None = None


class ConfigRevisionCreateRequest(StrictModel):
    merchant_config: dict[str, Any]


class KnowledgeJobResponse(StrictModel):
    job_id: str
    merchant_id: str
    status: Literal["queued", "running", "completed", "failed"]
    requested_by: str
    requested_at: str
    completed_at: str | None = None
    result: dict[str, int] | None = None
    error_code: str | None = None


class OrderSummaryResponse(StrictModel):
    order_id: str
    status: str
    created_at: str
    total_cents: int
    shipping_status: str | None


class SkillResponse(StrictModel):
    skill_id: str
    description: str
    input_schema: str
    output_schema: str
    tool_dependencies: list[str]
    enabled_in_merchant_config: bool
    implementation_status: Literal["planned", "active"]


class ChatStatus(str, Enum):
    COMPLETED = "completed"
    NEEDS_INFO = "needs_info"
    HANDED_OFF = "handed_off"
    FAILED = "failed"


class ChatRequest(StrictModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class TraceEvent(StrictModel):
    step: int = Field(ge=1)
    action: str
    status: Literal["success", "failed", "skipped"]
    summary: str
    error_code: str | None = None


class Citation(StrictModel):
    document_id: str
    filename: str
    paragraph_id: str
    excerpt: str


class HandoffInfo(StrictModel):
    ticket_id: str
    status: str
    created_at: str | None = None


class ChatError(StrictModel):
    code: str
    message: str


class IntentResponse(StrictModel):
    intent: str
    order_id: str | None
    rationale: str


class ChatResponse(StrictModel):
    session_id: str
    answer: str
    status: ChatStatus
    intents: list[IntentResponse]
    used_skills: list[str]
    sources: list[Citation]
    trace: list[TraceEvent]
    handoff: HandoffInfo | None
    error: ChatError | None
