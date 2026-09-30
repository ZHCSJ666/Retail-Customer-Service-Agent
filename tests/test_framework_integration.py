from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import LoadedMerchant, MerchantCatalog
from app.main import create_app
from tools.mock import MockOrderTool
from tools.registry import build_default_tool_adapter_registry


def test_v1_manifest_capabilities_config_validation_and_chat_alias(client: TestClient):
    manifest = client.get("/v1/framework")
    merchants = client.get("/v1/merchants")

    assert manifest.status_code == 200
    assert manifest.json()["api_version"] == "v1"
    assert "POST /v1/chat" in manifest.json()["chat_endpoints"]
    assert {item["adapter_id"] for item in manifest.json()["adapter_capabilities"]} == {
        "mock",
        "fixture_mock",
    }
    assert {merchant["merchant_id"] for merchant in merchants.json()} == {"star_select", "paper_harbor"}

    source_config = client.app.state.container.merchants.get("star_select").config.model_dump(mode="json")
    valid = client.post("/v1/framework/merchant-config/validate", json={"merchant_config": source_config})
    assert valid.status_code == 200
    assert valid.json()["valid"] is True

    source_config["tool_adapters"]["order"] = "acme_oms"
    source_config["enabled_skills"].append("custom_after_sales")
    unsupported = client.post(
        "/v1/framework/merchant-config/validate", json={"merchant_config": source_config}
    )
    assert unsupported.status_code == 200
    assert unsupported.json() == {
        "valid": False,
        "merchant_id": "star_select",
        "enabled_skills": [
            "knowledge_qa",
            "order_lookup",
            "refund_eligibility",
            "human_handoff",
            "custom_after_sales",
        ],
        "unknown_skill_ids": ["custom_after_sales"],
        "missing_tool_adapters": [],
        "unsupported_tool_adapters": {"order": "acme_oms"},
    }

    malformed = client.post(
        "/v1/framework/merchant-config/validate", json={"merchant_config": {"merchant_id": "BAD ID"}}
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "INVALID_MERCHANT_CONFIG"

    created = client.post("/v1/sessions", json={"merchant_id": "star_select", "customer_id": "CUS-1001"})
    assert created.status_code == 201
    chat = client.post(
        "/v1/chat", json={"session_id": created.json()["session_id"], "message": "我的订单到哪了？"}
    )
    assert chat.status_code == 200
    assert chat.json()["status"] == "needs_info"


def test_host_can_register_an_external_adapter_without_changing_agent_code(tmp_path: Path):
    catalog = MerchantCatalog()
    original = catalog.get("star_select")
    catalog._merchants["star_select"] = LoadedMerchant(  # test-specific configured merchant package
        config=original.config.model_copy(
            update={"tool_adapters": {**original.config.tool_adapters, "order": "recording_oms"}}
        ),
        source_path=original.source_path,
    )
    calls: list[tuple[str, str]] = []

    class RecordingOrderAdapter:
        def __init__(self, delegate: MockOrderTool) -> None:
            self.delegate = delegate

        def lookup_for_customer(self, *, customer_id: str, order_id: str):
            calls.append((customer_id, order_id))
            return self.delegate.lookup_for_customer(customer_id=customer_id, order_id=order_id)

    adapters = build_default_tool_adapter_registry()

    def build_recording_order(context):
        return RecordingOrderAdapter(
            MockOrderTool(context.demo_data, context.merchant.config.merchant_id)
        )

    adapters.register(
        tool_kind="order",
        adapter_id="recording_oms",
        description="Test host order-system adapter.",
        factory=build_recording_order,
    )
    app = create_app(
        database_path=tmp_path / "external_adapter.db",
        merchant_catalog=catalog,
        tool_adapters=adapters,
    )
    with TestClient(app) as client:
        session = client.post("/v1/sessions", json={"merchant_id": "star_select", "customer_id": "CUS-1001"})
        response = client.post(
            "/v1/chat",
            json={"session_id": session.json()["session_id"], "message": "SS-2026-10002 到哪了？"},
        )

    assert response.status_code == 200
    assert "运输中" in response.json()["answer"]
    assert calls == [("CUS-1001", "SS-2026-10002")]
