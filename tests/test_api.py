from fastapi.testclient import TestClient


def create_demo_session(client: TestClient, customer_id: str = "CUS-1001") -> dict:
    response = client.post("/sessions", json={"merchant_id": "star_select", "customer_id": customer_id})
    assert response.status_code == 201
    return response.json()


def test_health_and_declared_skill_contracts(client: TestClient):
    health = client.get("/health")
    skills = client.get("/skills")

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "retail-customer-agent",
        "database_ready": True,
        "llm_mode": "mock",
    }
    assert skills.status_code == 200
    payload = skills.json()
    assert [skill["skill_id"] for skill in payload] == [
        "knowledge_qa",
        "order_lookup",
        "refund_eligibility",
        "human_handoff",
    ]
    assert all(skill["enabled_in_merchant_config"] for skill in payload)
    statuses = {skill["skill_id"]: skill["implementation_status"] for skill in payload}
    assert statuses == {
        "knowledge_qa": "active",
        "order_lookup": "active",
        "refund_eligibility": "active",
        "human_handoff": "active",
    }


def test_http_only_manual_acceptance_page_is_served(client: TestClient):
    root = client.get("/", follow_redirects=False)
    response = client.get("/demo-ui")

    assert root.status_code == 307
    assert root.headers["location"] == "/demo-ui"
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "零售客户服务中心" in response.text
    assert "fetch(path" in response.text


def test_session_lifecycle_and_active_order_agent_response(client: TestClient):
    session = create_demo_session(client)
    session_id = session["session_id"]

    detail = client.get(f"/sessions/{session_id}")
    assert detail.status_code == 200
    assert detail.json()["customer_id"] == "CUS-1001"
    assert detail.json()["messages"] == []

    chat = client.post("/chat", json={"session_id": session_id, "message": "我的订单到哪了？"})
    assert chat.status_code == 200
    payload = chat.json()
    assert payload["status"] == "needs_info"
    assert payload["used_skills"] == ["order_lookup"]
    assert payload["intents"] == [
        {
            "intent": "order_lookup",
            "order_id": None,
            "rationale": "检测到订单/物流咨询或上一轮正在等待订单号。",
        }
    ]
    assert payload["sources"] == []
    assert payload["error"] is None
    assert any(event["action"] == "order_lookup" and event["status"] == "skipped" for event in payload["trace"])

    detail_after_chat = client.get(f"/sessions/{session_id}").json()
    assert [message["role"] for message in detail_after_chat["messages"]] == ["user", "assistant"]

    reset = client.post(f"/sessions/{session_id}/reset")
    assert reset.status_code == 200
    assert client.get(f"/sessions/{session_id}").json()["messages"] == []


def test_demo_orders_are_scoped_to_selected_demo_customer(client: TestClient):
    orders = client.get("/demo/orders", params={"customer_id": "CUS-1001"})
    assert orders.status_code == 200
    payload = orders.json()
    assert len(payload) == 4
    assert {order["status"] for order in payload} == {
        "pending_shipment",
        "in_transit",
        "delivered",
        "cancelled",
    }
    assert all("customer_id" not in order for order in payload)


def test_unknown_customer_and_session_are_rejected(client: TestClient):
    customer = client.post("/sessions", json={"customer_id": "CUS-4040"})
    missing_session = client.get("/sessions/not-a-real-session")

    assert customer.status_code == 404
    assert customer.json()["detail"]["code"] == "UNKNOWN_DEMO_CUSTOMER"
    assert missing_session.status_code == 404
    assert missing_session.json()["detail"]["code"] == "SESSION_NOT_FOUND"
