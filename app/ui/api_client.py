"""Small dependency-free HTTP client used by the Streamlit Demo."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ApiClientError(RuntimeError):
    """Safe, user-displayable API client error without request secrets."""


@dataclass(frozen=True)
class RetailApiClient:
    base_url: str
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        normalized = self.base_url.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("API 地址必须以 http:// 或 https:// 开头。")
        object.__setattr__(self, "base_url", normalized)

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def merchants(self) -> list[dict[str, Any]]:
        return self._request("GET", "/demo/merchants")

    def customers(self, merchant_id: str) -> list[dict[str, Any]]:
        return self._request("GET", "/demo/customers", params={"merchant_id": merchant_id})

    def orders(self, merchant_id: str, customer_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET", "/demo/orders", params={"merchant_id": merchant_id, "customer_id": customer_id}
        )

    def create_session(self, merchant_id: str, customer_id: str) -> dict[str, Any]:
        return self._request("POST", "/sessions", {"merchant_id": merchant_id, "customer_id": customer_id})

    def reset_session(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/sessions/{session_id}/reset", {})

    def chat(self, session_id: str, message: str) -> dict[str, Any]:
        return self._request("POST", "/chat", {"session_id": session_id, "message": message})

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None, params: dict[str, str] | None = None
    ) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - fixed configured API base URL
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = _error_detail(exc)
            raise ApiClientError(f"API 返回 {exc.code}：{detail}") from exc
        except URLError as exc:
            raise ApiClientError("无法连接 API，请确认 FastAPI 已启动且地址正确。") from exc
        except TimeoutError as exc:
            raise ApiClientError("请求 API 超时，请稍后重试。") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApiClientError("API 返回了无效 JSON。") from exc


def _error_detail(error: HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8"))
        detail = payload.get("detail", payload)
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("code") or "请求失败")
        return str(detail)
    except Exception:
        return "请求失败"
