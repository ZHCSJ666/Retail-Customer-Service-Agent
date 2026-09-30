from fastapi.testclient import TestClient

from app.main import create_app


def test_request_correlation_audit_metrics_and_handoff_event(client: TestClient):
    headers = {"X-Request-ID": "framework-op-test-001"}
    session = client.post(
        "/v1/sessions", json={"merchant_id": "star_select", "customer_id": "CUS-1001"}, headers=headers
    )
    assert session.status_code == 201
    assert session.headers["x-request-id"] == headers["X-Request-ID"]

    handoff = client.post(
        "/v1/chat",
        json={"session_id": session.json()["session_id"], "message": "我要人工客服"},
        headers=headers,
    )
    assert handoff.status_code == 200
    events = client.get("/v1/events", params={"merchant_id": "star_select"})
    assert events.status_code == 200
    assert events.json()[0]["event_type"] == "handoff.created"
    assert events.json()[0]["payload"]["ticket_id"] == handoff.json()["handoff"]["ticket_id"]

    audit = client.get("/v1/observability/audit", params={"merchant_id": "star_select"})
    metrics = client.get("/v1/observability/metrics", params={"merchant_id": "star_select"})
    assert {entry["action"] for entry in audit.json()} >= {"session.create", "chat.respond"}
    assert any(item["action"] == "chat.respond" and item["count"] >= 1 for item in metrics.json())
    assert all("message" not in entry["metadata"] for entry in audit.json())


def test_configuration_revision_activation_survives_restart_and_knowledge_job(client: TestClient):
    base_config = client.app.state.container.merchants.get("star_select").config.model_dump(mode="json")
    base_config["refund_rules"]["version"] = "star-select-runtime-v2"
    created = client.post("/v1/config/revisions", json={"merchant_config": base_config})
    assert created.status_code == 200
    assert created.json()["status"] == "draft"

    activated = client.post(f"/v1/config/revisions/{created.json()['revision_id']}/activate")
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert client.app.state.container.merchants.get("star_select").config.refund_rules.version == "star-select-runtime-v2"

    database_path = client.app.state.container.sessions.database_path
    restarted = create_app(database_path=database_path)
    assert restarted.state.container.merchants.get("star_select").config.refund_rules.version == "star-select-runtime-v2"

    job = client.post("/v1/knowledge/reindex", params={"merchant_id": "star_select"})
    assert job.status_code == 200
    assert job.json()["status"] == "completed"
    assert job.json()["result"]["documents"] == 5


def test_idempotency_key_replays_without_creating_a_second_session_or_event(client: TestClient):
    session_payload = {"merchant_id": "star_select", "customer_id": "CUS-1001"}
    headers = {"Idempotency-Key": "session-retry-key-001"}
    first = client.post("/v1/sessions", json=session_payload, headers=headers)
    replay = client.post("/v1/sessions", json=session_payload, headers=headers)
    assert first.status_code == replay.status_code == 201
    assert first.json()["session_id"] == replay.json()["session_id"]
    assert (
        client.post("/v1/sessions", json={**session_payload, "customer_id": "CUS-1002"}, headers=headers).status_code
        == 409
    )

    chat_headers = {"Idempotency-Key": "handoff-retry-key-001"}
    payload = {"session_id": first.json()["session_id"], "message": "我要人工客服"}
    handoff = client.post("/v1/chat", json=payload, headers=chat_headers)
    handoff_replay = client.post("/v1/chat", json=payload, headers=chat_headers)
    assert handoff.json()["handoff"]["ticket_id"] == handoff_replay.json()["handoff"]["ticket_id"]
    events = client.get("/v1/events", params={"merchant_id": "star_select"}).json()
    assert len([event for event in events if event["event_type"] == "handoff.created"]) == 1
