import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


STAR_KEY = "star-host-test-key-12345"
PAPER_KEY = "paper-host-test-key-6789"


def test_v1_api_key_authentication_and_merchant_isolation(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FRAMEWORK_AUTH_MODE", "api_key")
    monkeypatch.setenv(
        "FRAMEWORK_API_KEYS_JSON",
        json.dumps(
            [
                {"principal_id": "star_host", "api_key": STAR_KEY, "merchant_ids": ["star_select"]},
                {"principal_id": "paper_host", "api_key": PAPER_KEY, "merchant_ids": ["paper_harbor"]},
            ]
        ),
    )
    app = create_app(database_path=tmp_path / "secured_sessions.db")
    with TestClient(app) as client:
        missing_key = client.get("/v1/framework")
        legacy_health = client.get("/health")
        star_headers = {"X-Framework-Api-Key": STAR_KEY}
        paper_headers = {"X-Framework-Api-Key": PAPER_KEY}

        assert missing_key.status_code == 401
        assert missing_key.headers["www-authenticate"] == "ApiKey"
        assert legacy_health.status_code == 200  # Demo routes retain local backwards compatibility.

        manifest = client.get("/v1/framework", headers=star_headers)
        merchant_list = client.get("/v1/merchants", headers=star_headers)
        assert manifest.json()["authentication_mode"] == "api_key"
        assert [merchant["merchant_id"] for merchant in merchant_list.json()] == ["star_select"]
        assert client.get("/v1/merchants/paper_harbor", headers=star_headers).status_code == 403
        assert (
            client.post(
                "/v1/sessions",
                json={"merchant_id": "paper_harbor", "customer_id": "PH-CUS-01"},
                headers=star_headers,
            ).status_code
            == 403
        )

        paper_session = client.post(
            "/v1/sessions",
            json={"merchant_id": "paper_harbor", "customer_id": "PH-CUS-01"},
            headers=paper_headers,
        )
        assert paper_session.status_code == 201
        session_id = paper_session.json()["session_id"]

        assert client.get(f"/v1/sessions/{session_id}", headers=star_headers).status_code == 403
        assert (
            client.post(
                "/v1/chat",
                json={"session_id": session_id, "message": "这支笔防水吗？"},
                headers=star_headers,
            ).status_code
            == 403
        )
        allowed_chat = client.post(
            "/v1/chat",
            json={"session_id": session_id, "message": "这支笔防水吗？"},
            headers=paper_headers,
        )
        assert allowed_chat.status_code == 200
        assert "不防水" in allowed_chat.json()["answer"]
