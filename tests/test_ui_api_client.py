import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from app.ui.api_client import ApiClientError, RetailApiClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def test_client_encodes_query_and_chat_payload(monkeypatch):
    captured = []

    def fake_urlopen(request, timeout):
        captured.append((request, timeout))
        if request.get_method() == "GET":
            return FakeResponse([{"customer_id": "CUS-1001", "display_name": "林晓"}])
        return FakeResponse({"session_id": "s-1", "status": "completed"})

    monkeypatch.setattr("app.ui.api_client.urlopen", fake_urlopen)
    client = RetailApiClient("http://example.test/")

    customers = client.customers("star select")
    response = client.chat("s-1", "我的订单到哪了？")

    assert client.base_url == "http://example.test"
    assert customers[0]["display_name"] == "林晓"
    assert response["status"] == "completed"
    assert "merchant_id=star+select" in captured[0][0].full_url
    assert json.loads(captured[1][0].data.decode("utf-8")) == {
        "session_id": "s-1",
        "message": "我的订单到哪了？",
    }


def test_client_converts_http_error_to_safe_display_message(monkeypatch):
    def fake_urlopen(_request, timeout):
        raise HTTPError(
            "http://example.test/health",
            503,
            "unavailable",
            hdrs=None,
            fp=BytesIO(b'{"detail":{"code":"SERVICE_DOWN","message":"service unavailable"}}'),
        )

    monkeypatch.setattr("app.ui.api_client.urlopen", fake_urlopen)

    with pytest.raises(ApiClientError, match="API 返回 503：service unavailable"):
        RetailApiClient("http://example.test").health()
