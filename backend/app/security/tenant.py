"""Server-derived tenant identity for request and background-work isolation."""

from __future__ import annotations

from contextvars import ContextVar, Token

LOCAL_TENANT_ID = "local"
_tenant_id: ContextVar[str] = ContextVar("code_sonar_tenant_id", default=LOCAL_TENANT_ID)


def current_tenant_id() -> str:
    """Return the tenant bound by the authenticated API boundary."""
    return _tenant_id.get()


def bind_tenant(tenant_id: str) -> Token[str]:
    """Bind a validated server-derived tenant for the current async context."""
    return _tenant_id.set(tenant_id)


def reset_tenant(token: Token[str]) -> None:
    _tenant_id.reset(token)
