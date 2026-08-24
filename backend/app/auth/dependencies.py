"""FastAPI dependencies for authentication."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import User, UserInDB
from app.auth.session import SessionManager, get_session_manager

# Bearer token scheme
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session_manager: SessionManager = Depends(get_session_manager),
) -> User:
    """Get the current authenticated user from the access token.

    Raises 401 if no valid token is provided.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    session = session_manager.get_by_access_token(credentials.credentials)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Load user from database (in-memory for now)
    user = _get_user_by_id(session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Touch session to update last_used_at
    session_manager.touch_session(session.access_token)

    return user.to_public()


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session_manager: SessionManager = Depends(get_session_manager),
) -> User | None:
    """Get the current user if authenticated, otherwise None."""
    if credentials is None:
        return None

    session = session_manager.get_by_access_token(credentials.credentials)
    if session is None:
        return None

    user = _get_user_by_id(session.user_id)
    if user is None or not user.is_active:
        return None

    session_manager.touch_session(session.access_token)
    return user.to_public()


def require_user(user: User = Depends(get_current_user)) -> User:
    """Require an authenticated user (same as get_current_user, explicit intent)."""
    return user


# In-memory user store (replace with database in production)
_user_store: dict[str, UserInDB] = {}  # email -> UserInDB
_user_id_index: dict[str, str] = {}  # user_id -> email


def _get_user_by_id(user_id: str) -> UserInDB | None:
    email = _user_id_index.get(user_id)
    if email:
        return _user_store.get(email)
    return None


def _get_user_by_email(email: str) -> UserInDB | None:
    return _user_store.get(email.lower())


def _save_user(user: UserInDB) -> None:
    _user_store[user.email] = user
    _user_id_index[user.id] = user.email


def get_user_store() -> dict[str, UserInDB]:
    """Get the user store (for testing/admin)."""
    return _user_store


def set_user_store(store: dict[str, UserInDB]) -> None:
    """Replace the user store (for testing)."""
    global _user_store, _user_id_index
    _user_store = store
    _user_id_index = {u.id: e for e, u in store.items()}