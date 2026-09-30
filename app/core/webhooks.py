"""A small durable-outbox webhook dispatcher with HMAC signatures and replay."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.core.framework_store import FrameworkStore


class WebhookDispatcher:
    def __init__(self, store: FrameworkStore) -> None:
        self.store = store
        self.url = os.getenv("FRAMEWORK_WEBHOOK_URL", "").strip()
        self.secret = os.getenv("FRAMEWORK_WEBHOOK_SECRET", "")
        if self.url and len(self.secret) < 16:
            raise RuntimeError("FRAMEWORK_WEBHOOK_SECRET must contain at least 16 characters when webhooks are enabled")

    def dispatch(self, event_id: str) -> dict[str, object] | None:
        event = self.store.get_event(event_id)
        if event is None:
            return None
        if not self.url:
            self.store.mark_event_delivery(event_id=event_id, status="not_configured")
            return self.store.get_event(event_id)
        body = json.dumps({key: event[key] for key in ("event_id", "merchant_id", "event_type", "request_id", "payload", "created_at")}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        try:
            request = Request(self.url, data=body, method="POST", headers={"Content-Type": "application/json", "X-Framework-Signature": f"sha256={signature}", "X-Framework-Event": str(event["event_type"])})
            with urlopen(request, timeout=5) as response:  # noqa: S310 - explicit deployment webhook URL
                if not 200 <= response.status < 300:
                    raise URLError(f"webhook returned HTTP {response.status}")
        except (URLError, TimeoutError, OSError):
            self.store.mark_event_delivery(event_id=event_id, status="failed", error="WEBHOOK_DELIVERY_FAILED")
        else:
            self.store.mark_event_delivery(event_id=event_id, status="delivered")
        return self.store.get_event(event_id)
