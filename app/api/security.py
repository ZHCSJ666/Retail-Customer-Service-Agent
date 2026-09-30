"""Optional host API-key authentication and merchant access boundaries for /v1."""

from __future__ import annotations

from dataclasses import dataclass
from secrets import compare_digest

from fastapi import Depends, HTTPException, Request, status

from app.api.dependencies import get_container
from app.container import AppContainer


@dataclass(frozen=True)
class IntegrationPrincipal:
    principal_id: str
    merchant_ids: frozenset[str] | None

    def permits(self, merchant_id: str) -> bool:
        return self.merchant_ids is None or merchant_id in self.merchant_ids


def require_integration_principal(
    request: Request, container: AppContainer = Depends(get_container)
) -> IntegrationPrincipal:
    """Authenticate only framework /v1 routes; legacy local Demo routes stay unchanged."""
    settings = container.settings
    if settings.framework_auth_mode == "disabled":
        principal = IntegrationPrincipal(principal_id="local-demo", merchant_ids=None)
    else:
        supplied_key = request.headers.get("X-Framework-Api-Key", "")
        configured = next(
            (
                candidate
                for candidate in settings.integration_principals
                if supplied_key and compare_digest(supplied_key, candidate.api_key)
            ),
            None,
        )
        if configured is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INTEGRATION_AUTH_REQUIRED", "message": "缺少或无效的框架 API Key。"},
                headers={"WWW-Authenticate": "ApiKey"},
            )
        principal = IntegrationPrincipal(
            principal_id=configured.principal_id,
            merchant_ids=frozenset(configured.merchant_ids),
        )
    request.state.integration_principal = principal
    return principal


def authorize_integration_merchant(request: Request, merchant_id: str) -> None:
    """Enforce an authenticated host's merchant scope when the route is /v1."""
    principal = getattr(request.state, "integration_principal", None)
    if principal is not None and not principal.permits(merchant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "MERCHANT_ACCESS_DENIED", "message": "当前接入方无权访问该商家。"},
        )


def integration_principal_from_request(request: Request) -> IntegrationPrincipal | None:
    return getattr(request.state, "integration_principal", None)
