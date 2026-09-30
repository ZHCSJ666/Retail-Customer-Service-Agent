"""HTTP API endpoints for demo context, sessions and Agent chat."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import ValidationError

from app.api.dependencies import get_container
from app.api.security import (
    authorize_integration_merchant,
    integration_principal_from_request,
    require_integration_principal,
)
from app.container import AppContainer
from app.core.config import LoadedMerchant, MerchantConfig
from app.core.skill_catalog import CORE_SKILLS, configured_skills
from app.schemas.api import (
    AdapterCapabilityResponse,
    AuditEventResponse,
    ChatError,
    ChatRequest,
    ChatResponse,
    ChatStatus,
    ConfigRevisionCreateRequest,
    ConfigRevisionResponse,
    CustomerResponse,
    FrameworkEventResponse,
    FrameworkManifestResponse,
    HealthResponse,
    MerchantCapabilityResponse,
    MerchantConfigValidationRequest,
    MerchantConfigValidationResponse,
    MerchantResponse,
    MetricCountResponse,
    KnowledgeJobResponse,
    MessageResponse,
    OrderSummaryResponse,
    SessionCreateRequest,
    SessionDetailResponse,
    SessionResponse,
    SkillResponse,
    TraceEvent,
)
from rag.ingest import ingest_merchant_knowledge


router = APIRouter()
integration_router = APIRouter(prefix="/v1", dependencies=[Depends(require_integration_principal)])
FALLBACK_DEMO_UI = Path(__file__).resolve().parents[1] / "ui" / "fallback_demo.html"


def _session_or_404(container: AppContainer, session_id: str) -> dict[str, str]:
    session = container.sessions.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在。"})
    return session


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Make a forwarded-port click open the customer-service workspace directly."""
    return RedirectResponse(url="/demo-ui", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/health", response_model=HealthResponse, tags=["system"])
@integration_router.get("/health", response_model=HealthResponse, tags=["integration"])
def health(container: AppContainer = Depends(get_container)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="retail-customer-agent",
        database_ready=container.sessions.ping(),
        llm_mode=container.settings.llm_mode,
    )


@router.get("/demo-ui", include_in_schema=False)
def fallback_demo_ui() -> FileResponse:
    """Serve an HTTP-only manual acceptance UI when Streamlit preview is unavailable."""
    return FileResponse(FALLBACK_DEMO_UI, media_type="text/html; charset=utf-8")


@integration_router.get("/framework", response_model=FrameworkManifestResponse, tags=["integration"])
def framework_manifest(container: AppContainer = Depends(get_container)) -> FrameworkManifestResponse:
    """Discover stable v1 routes and extension seams without exposing local paths or secrets."""
    return FrameworkManifestResponse(
        api_version="v1",
        authentication_mode=container.settings.framework_auth_mode,
        chat_endpoints=[
            "POST /v1/sessions",
            "GET /v1/sessions/{session_id}",
            "POST /v1/sessions/{session_id}/reset",
            "POST /v1/chat",
        ],
        extension_points=[
            "merchant YAML/JSON contract validation",
            "host-registered product/order/shipping/handoff adapters",
            "registered Skill Pack and per-merchant enabled_skills",
        ],
        identity_boundary=(
            "已启用接入方 API Key；宿主仍必须在创建会话前认证终端用户，customer_id 只能是可信上下文。"
            if container.settings.framework_auth_mode == "api_key"
            else "本地模式未启用接入方鉴权；生产接入前必须启用 API Key，并由宿主认证终端用户。"
        ),
        adapter_capabilities=[AdapterCapabilityResponse(**item) for item in container.tool_adapters.capabilities()],
    )


@integration_router.get("/observability/audit", response_model=list[AuditEventResponse], tags=["operations"])
def list_audit_events(
    request: Request,
    merchant_id: str | None = None,
    limit: int = 50,
    container: AppContainer = Depends(get_container),
) -> list[AuditEventResponse]:
    principal = integration_principal_from_request(request)
    if merchant_id is not None:
        authorize_integration_merchant(request, merchant_id)
    elif principal is not None and principal.merchant_ids is not None:
        # The route must not return cross-merchant audit events for a scoped principal.
        raise HTTPException(status_code=400, detail={"code": "MERCHANT_ID_REQUIRED", "message": "受限接入方必须指定 merchant_id。"})
    bounded_limit = min(max(limit, 1), 100)
    return [AuditEventResponse(**item) for item in container.framework_store.list_audit(merchant_id=merchant_id, limit=bounded_limit)]


@integration_router.get("/observability/metrics", response_model=list[MetricCountResponse], tags=["operations"])
def framework_metrics(
    request: Request,
    merchant_id: str | None = None,
    container: AppContainer = Depends(get_container),
) -> list[MetricCountResponse]:
    principal = integration_principal_from_request(request)
    if merchant_id is not None:
        authorize_integration_merchant(request, merchant_id)
    elif principal is not None and principal.merchant_ids is not None:
        raise HTTPException(status_code=400, detail={"code": "MERCHANT_ID_REQUIRED", "message": "受限接入方必须指定 merchant_id。"})
    return [MetricCountResponse(**item) for item in container.framework_store.metric_counts(merchant_id=merchant_id)]


@integration_router.get("/events", response_model=list[FrameworkEventResponse], tags=["operations"])
def list_framework_events(
    request: Request,
    merchant_id: str,
    limit: int = 50,
    container: AppContainer = Depends(get_container),
) -> list[FrameworkEventResponse]:
    authorize_integration_merchant(request, merchant_id)
    return [
        FrameworkEventResponse(**item)
        for item in container.framework_store.list_events(merchant_id=merchant_id, limit=min(max(limit, 1), 100))
    ]


@integration_router.post("/events/{event_id}/replay", response_model=FrameworkEventResponse, tags=["operations"])
def replay_framework_event(
    event_id: str, request: Request, container: AppContainer = Depends(get_container)
) -> FrameworkEventResponse:
    event = container.framework_store.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail={"code": "EVENT_NOT_FOUND", "message": "事件不存在。"})
    authorize_integration_merchant(request, str(event["merchant_id"]))
    delivered = container.webhooks.dispatch(event_id)
    _audit_integration(request, container, merchant_id=str(event["merchant_id"]), action="event.replay", outcome=str(delivered["delivery_status"]), metadata={"event_id": event_id})
    return FrameworkEventResponse(**delivered)


@integration_router.get(
    "/merchants", response_model=list[MerchantCapabilityResponse], tags=["integration"]
)
def integration_merchants(
    request: Request, container: AppContainer = Depends(get_container)
) -> list[MerchantCapabilityResponse]:
    principal = integration_principal_from_request(request)
    return [
        _merchant_capability(merchant)
        for merchant in container.merchants.all()
        if principal is None or principal.permits(merchant.config.merchant_id)
    ]


@integration_router.get(
    "/merchants/{merchant_id}", response_model=MerchantCapabilityResponse, tags=["integration"]
)
def integration_merchant(
    merchant_id: str, request: Request, container: AppContainer = Depends(get_container)
) -> MerchantCapabilityResponse:
    authorize_integration_merchant(request, merchant_id)
    try:
        return _merchant_capability(container.merchants.get(merchant_id))
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "MERCHANT_NOT_FOUND", "message": "商家不存在。"},
        ) from None


@integration_router.post(
    "/framework/merchant-config/validate",
    response_model=MerchantConfigValidationResponse,
    tags=["integration"],
)
def validate_merchant_config(
    request: Request,
    payload: MerchantConfigValidationRequest,
    container: AppContainer = Depends(get_container),
) -> MerchantConfigValidationResponse:
    """Validate a YAML-equivalent merchant config without persisting it or loading code/files."""
    try:
        config = MerchantConfig.model_validate(payload.merchant_config)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_MERCHANT_CONFIG",
                "message": "商家配置不符合框架契约。",
                "errors": exc.errors(include_url=False, include_context=False),
            },
        ) from None
    candidate = LoadedMerchant(config=config, source_path=Path("<api-validation>"))
    authorize_integration_merchant(request, config.merchant_id)
    missing, unsupported = container.tool_adapters.validate_merchant(candidate)
    known_skill_ids = {skill.skill_id for skill in CORE_SKILLS}
    unknown_skills = [skill_id for skill_id in config.enabled_skills if skill_id not in known_skill_ids]
    return MerchantConfigValidationResponse(
        valid=not missing and not unsupported and not unknown_skills,
        merchant_id=config.merchant_id,
        enabled_skills=config.enabled_skills,
        unknown_skill_ids=unknown_skills,
        missing_tool_adapters=missing,
        unsupported_tool_adapters=unsupported,
    )


@integration_router.post("/config/revisions", response_model=ConfigRevisionResponse, tags=["operations"])
def create_config_revision(
    request: Request,
    payload: ConfigRevisionCreateRequest,
    container: AppContainer = Depends(get_container),
) -> ConfigRevisionResponse:
    config = _validated_runtime_config(payload.merchant_config, container)
    authorize_integration_merchant(request, config.merchant_id)
    principal = integration_principal_from_request(request)
    record = container.framework_store.create_config_revision(
        merchant_id=config.merchant_id, config=config.model_dump(mode="json"), created_by=principal.principal_id
    )
    _audit_integration(request, container, merchant_id=config.merchant_id, action="config.revision.create", outcome="success", metadata={"revision_id": record["revision_id"], "version": record["version"]})
    return ConfigRevisionResponse(**record)


@integration_router.get("/config/revisions", response_model=list[ConfigRevisionResponse], tags=["operations"])
def list_config_revisions(
    request: Request, merchant_id: str, container: AppContainer = Depends(get_container)
) -> list[ConfigRevisionResponse]:
    authorize_integration_merchant(request, merchant_id)
    return [ConfigRevisionResponse(**record) for record in container.framework_store.list_config_revisions(merchant_id)]


@integration_router.post("/config/revisions/{revision_id}/activate", response_model=ConfigRevisionResponse, tags=["operations"])
def activate_config_revision(
    revision_id: str, request: Request, container: AppContainer = Depends(get_container)
) -> ConfigRevisionResponse:
    record = container.framework_store.get_config_revision(revision_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "CONFIG_REVISION_NOT_FOUND", "message": "配置修订不存在。"})
    authorize_integration_merchant(request, str(record["merchant_id"]))
    config = _validated_runtime_config(record["config"], container)
    loaded = container.merchants.upsert_runtime_config(config)
    try:
        ingest_merchant_knowledge(loaded, container.rag_store)
    except Exception as exc:
        raise HTTPException(status_code=422, detail={"code": "KNOWLEDGE_INGEST_FAILED", "message": "配置资料无法建立知识索引。"}) from exc
    activated = container.framework_store.activate_config_revision(revision_id)
    _audit_integration(request, container, merchant_id=config.merchant_id, action="config.revision.activate", outcome="success", metadata={"revision_id": revision_id})
    return ConfigRevisionResponse(**activated)


@integration_router.post("/knowledge/reindex", response_model=KnowledgeJobResponse, tags=["operations"])
def reindex_knowledge(
    request: Request, merchant_id: str, container: AppContainer = Depends(get_container)
) -> KnowledgeJobResponse:
    authorize_integration_merchant(request, merchant_id)
    principal = integration_principal_from_request(request)
    job = container.framework_store.create_knowledge_job(merchant_id=merchant_id, requested_by=principal.principal_id)
    try:
        result = ingest_merchant_knowledge(container.merchants.get(merchant_id), container.rag_store)
        container.framework_store.complete_knowledge_job(job_id=job["job_id"], result=result, error_code=None)
        _audit_integration(request, container, merchant_id=merchant_id, action="knowledge.reindex", outcome="success", metadata={"job_id": job["job_id"], **result})
    except Exception:
        container.framework_store.complete_knowledge_job(job_id=job["job_id"], result=None, error_code="KNOWLEDGE_INDEX_FAILED")
    return KnowledgeJobResponse(**container.framework_store.get_knowledge_job(job["job_id"]))


@integration_router.get("/knowledge/jobs/{job_id}", response_model=KnowledgeJobResponse, tags=["operations"])
def get_knowledge_job(job_id: str, request: Request, container: AppContainer = Depends(get_container)) -> KnowledgeJobResponse:
    job = container.framework_store.get_knowledge_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "KNOWLEDGE_JOB_NOT_FOUND", "message": "知识任务不存在。"})
    authorize_integration_merchant(request, str(job["merchant_id"]))
    return KnowledgeJobResponse(**job)


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED, tags=["sessions"])
@integration_router.post(
    "/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED, tags=["integration"]
)
def create_session(
    payload: SessionCreateRequest, request: Request, container: AppContainer = Depends(get_container)
) -> SessionResponse:
    authorize_integration_merchant(request, payload.merchant_id)
    replay = _idempotent_replay(request, container, "session.create", payload.model_dump(), SessionResponse)
    if replay is not None:
        return replay
    try:
        container.merchants.get(payload.merchant_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "MERCHANT_NOT_FOUND", "message": "模拟商家不存在。"},
        ) from None

    if not container.demo_data.customer_exists(payload.merchant_id, payload.customer_id):
        raise HTTPException(
            status_code=404,
            detail={"code": "UNKNOWN_DEMO_CUSTOMER", "message": "该模拟商家中不存在此客户。"},
        )
    created = SessionResponse(**container.sessions.create_session(payload.merchant_id, payload.customer_id))
    _audit_integration(
        request,
        container,
        merchant_id=payload.merchant_id,
        action="session.create",
        outcome="success",
        metadata={"session_id": created.session_id},
    )
    _save_idempotent_response(request, container, "session.create", payload.model_dump(), created)
    return created


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse, tags=["sessions"])
@integration_router.get(
    "/sessions/{session_id}", response_model=SessionDetailResponse, tags=["integration"]
)
def get_session(
    session_id: str, request: Request, container: AppContainer = Depends(get_container)
) -> SessionDetailResponse:
    session = _session_or_404(container, session_id)
    authorize_integration_merchant(request, session["merchant_id"])
    messages = [MessageResponse(**message) for message in container.sessions.list_messages(session_id)]
    return SessionDetailResponse(**session, messages=messages)


@router.post("/sessions/{session_id}/reset", response_model=SessionResponse, tags=["sessions"])
@integration_router.post(
    "/sessions/{session_id}/reset", response_model=SessionResponse, tags=["integration"]
)
def reset_session(session_id: str, request: Request, container: AppContainer = Depends(get_container)) -> SessionResponse:
    session = _session_or_404(container, session_id)
    authorize_integration_merchant(request, session["merchant_id"])
    container.sessions.reset_session(session_id)
    refreshed = _session_or_404(container, session_id)
    return SessionResponse(**refreshed)


@router.get("/skills", response_model=list[SkillResponse], tags=["configuration"])
@integration_router.get("/skills", response_model=list[SkillResponse], tags=["integration"])
def list_skills(
    request: Request, merchant_id: str = "star_select", container: AppContainer = Depends(get_container)
) -> list[SkillResponse]:
    authorize_integration_merchant(request, merchant_id)
    try:
        merchant = container.merchants.get(merchant_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "MERCHANT_NOT_FOUND", "message": "模拟商家不存在。"},
        ) from None
    return [
        SkillResponse(**skill)
        for skill in configured_skills(merchant.config.enabled_skills, container.agent.active_skill_ids)
    ]


@router.get("/demo/merchants", response_model=list[MerchantResponse], tags=["demo"])
def list_demo_merchants(container: AppContainer = Depends(get_container)) -> list[MerchantResponse]:
    return [
        MerchantResponse(
            merchant_id=merchant.config.merchant_id,
            display_name=merchant.config.display_name,
            demo_disclaimer=merchant.config.demo_disclaimer,
        )
        for merchant in container.merchants.all()
    ]


@router.get("/demo/customers", response_model=list[CustomerResponse], tags=["demo"])
def list_demo_customers(
    merchant_id: str = "star_select", container: AppContainer = Depends(get_container)
) -> list[CustomerResponse]:
    try:
        customers = container.demo_data.customers(merchant_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "MERCHANT_NOT_FOUND", "message": "模拟商家不存在。"},
        ) from None
    return [
        CustomerResponse(customer_id=str(customer["customer_id"]), display_name=str(customer["display_name"]))
        for customer in customers
    ]


@router.get("/demo/orders", response_model=list[OrderSummaryResponse], tags=["demo"])
def list_demo_orders(
    customer_id: str, merchant_id: str = "star_select", container: AppContainer = Depends(get_container)
) -> list[OrderSummaryResponse]:
    """Lists orders for the selected demo identity; this endpoint is not authentication.

    Phase 2 tools will obtain the trusted customer ID from a session and enforce
    ownership again before disclosing an order in chat.
    """

    try:
        customer_exists = container.demo_data.customer_exists(merchant_id, customer_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "MERCHANT_NOT_FOUND", "message": "模拟商家不存在。"},
        ) from None
    if not customer_exists:
        raise HTTPException(
            status_code=404,
            detail={"code": "UNKNOWN_DEMO_CUSTOMER", "message": "该模拟商家中不存在此客户。"},
        )
    orders = container.demo_data.orders_for_customer(merchant_id, customer_id)
    return [
        OrderSummaryResponse(
            order_id=str(order["order_id"]),
            status=str(order["status"]),
            created_at=str(order["created_at"]),
            total_cents=int(order["total_cents"]),
            shipping_status=(order.get("shipping") or {}).get("status"),
        )
        for order in orders
    ]


@router.post("/chat", response_model=ChatResponse, tags=["chat"])
@integration_router.post("/chat", response_model=ChatResponse, tags=["integration"])
def chat(
    payload: ChatRequest, request: Request, container: AppContainer = Depends(get_container)
) -> ChatResponse:
    """Run the bounded Agent flow for an existing, trusted demo session."""
    session = _session_or_404(container, payload.session_id)
    authorize_integration_merchant(request, session["merchant_id"])
    replay = _idempotent_replay(request, container, "chat.respond", payload.model_dump(), ChatResponse)
    if replay is not None:
        return replay
    response = container.agent.respond(session_id=payload.session_id, message=payload.message)
    _audit_integration(
        request,
        container,
        merchant_id=session["merchant_id"],
        action="chat.respond",
        outcome=response.status.value,
        metadata={"session_id": payload.session_id, "used_skills": response.used_skills},
    )
    _emit_framework_events(request, container, merchant_id=session["merchant_id"], response=response)
    _save_idempotent_response(request, container, "chat.respond", payload.model_dump(), response)
    return response


def _merchant_capability(merchant: LoadedMerchant) -> MerchantCapabilityResponse:
    config = merchant.config
    return MerchantCapabilityResponse(
        merchant_id=config.merchant_id,
        display_name=config.display_name,
        enabled_skills=config.enabled_skills,
        order_id_pattern=config.order_id_pattern,
        tool_adapters=config.tool_adapters,
    )


def _audit_integration(
    request: Request,
    container: AppContainer,
    *,
    merchant_id: str | None,
    action: str,
    outcome: str,
    metadata: dict[str, object],
) -> None:
    principal = integration_principal_from_request(request)
    if principal is None:
        return
    container.framework_store.record_audit(
        request_id=getattr(request.state, "request_id", "unknown"),
        principal_id=principal.principal_id,
        merchant_id=merchant_id,
        action=action,
        outcome=outcome,
        metadata=metadata,
    )


def _emit_framework_events(
    request: Request, container: AppContainer, *, merchant_id: str, response: ChatResponse
) -> None:
    request_id = getattr(request.state, "request_id", "unknown")
    if response.handoff is not None:
        event = container.framework_store.create_event(
            merchant_id=merchant_id,
            event_type="handoff.created",
            request_id=request_id,
            payload={"session_id": response.session_id, "ticket_id": response.handoff.ticket_id, "status": response.handoff.status},
        )
        container.webhooks.dispatch(str(event["event_id"]))
    if "refund_eligibility" in response.used_skills:
        event = container.framework_store.create_event(
            merchant_id=merchant_id,
            event_type="refund.eligibility.decided",
            request_id=request_id,
            payload={"session_id": response.session_id, "status": response.status.value},
        )
        container.webhooks.dispatch(str(event["event_id"]))


def _validated_runtime_config(raw_config: object, container: AppContainer) -> MerchantConfig:
    try:
        config = MerchantConfig.model_validate(raw_config)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_MERCHANT_CONFIG", "message": "商家配置不符合框架契约。", "errors": exc.errors(include_url=False, include_context=False)},
        ) from None
    candidate = LoadedMerchant(config=config, source_path=Path("<runtime-config>"))
    missing, unsupported = container.tool_adapters.validate_merchant(candidate)
    unknown_skills = [skill_id for skill_id in config.enabled_skills if skill_id not in {skill.skill_id for skill in CORE_SKILLS}]
    if missing or unsupported or unknown_skills:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UNAVAILABLE_FRAMEWORK_CAPABILITY",
                "message": "配置引用了未注册的 Skill 或适配器。",
                "unknown_skill_ids": unknown_skills,
                "missing_tool_adapters": missing,
                "unsupported_tool_adapters": unsupported,
            },
        )
    return config


def _idempotent_replay(
    request: Request, container: AppContainer, operation: str, payload: dict[str, object], response_model: type
) -> object | None:
    principal = integration_principal_from_request(request)
    key = request.headers.get("Idempotency-Key", "").strip()
    if principal is None or not key:
        return None
    if len(key) > 128:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IDEMPOTENCY_KEY", "message": "Idempotency-Key 过长。"})
    existing = container.framework_store.get_idempotent_response(
        principal_id=principal.principal_id, operation=operation, idempotency_key=key
    )
    if existing is None:
        return None
    request_hash = _payload_hash(payload)
    if existing["request_hash"] != request_hash:
        raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "同一幂等键不能用于不同请求。"})
    return response_model.model_validate(json.loads(existing["response_json"]))


def _save_idempotent_response(
    request: Request, container: AppContainer, operation: str, payload: dict[str, object], response: object
) -> None:
    principal = integration_principal_from_request(request)
    key = request.headers.get("Idempotency-Key", "").strip()
    if principal is None or not key:
        return
    container.framework_store.save_idempotent_response(
        principal_id=principal.principal_id,
        operation=operation,
        idempotency_key=key,
        request_hash=_payload_hash(payload),
        response=response.model_dump(mode="json"),
    )


def _payload_hash(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
