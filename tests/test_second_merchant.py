import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import MerchantCatalog
from app.demo_data.repository import DemoDataRepository


def test_paper_harbor_is_an_independent_minimal_merchant_fixture():
    catalog = MerchantCatalog()
    merchant = catalog.get("paper_harbor")
    counts = DemoDataRepository(catalog).validate_merchant_fixtures("paper_harbor")

    assert merchant.config.display_name.startswith("纸舟文具")
    assert merchant.config.order_id_pattern == r"PH-\d{4}-\d{3}"
    assert merchant.config.tool_adapters["order"] == "fixture_mock"
    assert counts == {
        "products": 2,
        "customers": 1,
        "orders": 2,
        "knowledge_documents": 2,
        "failure_scenarios": 1,
    }


def test_api_switches_to_second_merchant_without_agent_code_change(client: TestClient):
    merchants = client.get("/demo/merchants")
    assert merchants.status_code == 200
    assert {merchant["merchant_id"] for merchant in merchants.json()} == {"star_select", "paper_harbor"}

    created = client.post(
        "/sessions", json={"merchant_id": "paper_harbor", "customer_id": "PH-CUS-01"}
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    orders = client.get(
        "/demo/orders", params={"merchant_id": "paper_harbor", "customer_id": "PH-CUS-01"}
    )
    assert {order["order_id"] for order in orders.json()} == {"PH-2026-001", "PH-2026-002"}

    knowledge = client.post(
        "/chat", json={"session_id": session_id, "message": "这支笔防水吗？"}
    ).json()
    assert knowledge["status"] == "completed"
    assert knowledge["used_skills"] == ["knowledge_qa"]
    assert "不防水" in knowledge["answer"]
    assert "products.md" in {source["filename"] for source in knowledge["sources"]}

    ask_order = client.post("/chat", json={"session_id": session_id, "message": "我的订单到哪了？"}).json()
    lookup = client.post("/chat", json={"session_id": session_id, "message": "PH-2026-001"}).json()
    assert ask_order["status"] == "needs_info"
    assert lookup["status"] == "completed"
    assert lookup["intents"][0]["order_id"] == "PH-2026-001"
    assert "速写中性笔" in lookup["answer"]


def test_init_demo_can_validate_and_ingest_every_merchant(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/init_demo.py",
            "--all-merchants",
            "--database",
            str(tmp_path / "all_merchants.db"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["database_ready"] is True
    by_merchant = {item["merchant_id"]: item for item in payload["merchants"]}
    assert by_merchant["star_select"]["knowledge_index"]["documents"] == 5
    assert by_merchant["paper_harbor"]["knowledge_index"]["documents"] == 2
