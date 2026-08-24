"""Session management for authentication."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from app.auth.models import UserInDB
from app.auth.password import generate_secure_token


# Token configuration
ACCESS_TOKEN_TTL_SECONDS: int = 3600  # 1 hour
REFRESH_TOKEN_TTL_SECONDS: int = 604800  # 7 days
SESSION_TOKEN_BYTES: int = 32


@dataclass
class Session:
    """User session with access and refresh tokens."""

    id: str
    user_id: str
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    created_at: datetime = field(default_factory=datetime.now)
    last_used_at: datetime = field(default_factory=datetime.now)
    user_agent: str | None = None
    ip_address: str | None = None
    is_revoked: bool = False

    def is_access_expired(self) -> bool:
        return datetime.now() >= self.access_expires_at

    def is_refresh_expired(self) -> bool:
        return datetime.now() >= self.refresh_expires_at

    def is_valid(self) -> bool:
        return not self.is_revoked and not self.is_refresh_expired()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "access_expires_at": self.access_expires_at.isoformat(),
            "refresh_expires_at": self.refresh_expires_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat(),
            "user_agent": self.user_agent,
            "ip_address": self.ip_address,
            "is_revoked": self.is_revoked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            access_expires_at=datetime.fromisoformat(data["access_expires_at"]),
            refresh_expires_at=datetime.fromisoformat(data["refresh_expires_at"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_used_at=datetime.fromisoformat(data["last_used_at"]),
            user_agent=data.get("user_agent"),
            ip_address=data.get("ip_address"),
            is_revoked=data.get("is_revoked", False),
        )


class SessionManager:
    """In-memory session manager. Replace with Redis/database for production."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}  # access_token -> Session
        self._refresh_index: dict[str, str] = {}  # refresh_token -> access_token
        self._user_sessions: dict[str, set[str]] = {}  # user_id -> set of access_tokens

    def create_session(
        self,
        user: UserInDB,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> Session:
        """Create a new session for a user."""
        now = datetime.now()
        access_token = generate_secure_token(SESSION_TOKEN_BYTES)
        refresh_token = generate_secure_token(SESSION_TOKEN_BYTES)

        session = Session(
            id=str(uuid4()),
            user_id=user.id,
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
            refresh_expires_at=now + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
            user_agent=user_agent,
            ip_address=ip_address,
        )

        self._sessions[access_token] = session
        self._refresh_index[refresh_token] = access_token
        self._user_sessions.setdefault(user.id, set()).add(access_token)

        return session

    def get_by_access_token(self, access_token: str) -> Session | None:
        """Get session by access token."""
        session = self._sessions.get(access_token)
        if session and not session.is_valid():
            self.revoke_session(access_token)
            return None
        return session

    def get_by_refresh_token(self, refresh_token: str) -> Session | None:
        """Get session by refresh token."""
        access_token = self._refresh_index.get(refresh_token)
        if access_token:
            return self.get_by_access_token(access_token)
        return None

    def refresh_access_token(self, refresh_token: str) -> Session | None:
        """Rotate access token using a valid refresh token."""
        session = self.get_by_refresh_token(refresh_token)
        if not session:
            return None

        # Revoke old access token
        self._revoke_access_token(session.access_token)

        # Create new access token (keep same refresh token)
        now = datetime.now()
        new_access_token = generate_secure_token(SESSION_TOKEN_BYTES)
        session.access_token = new_access_token
        session.access_expires_at = now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS)
        session.last_used_at = now

        self._sessions[new_access_token] = session
        self._refresh_index[refresh_token] = new_access_token
        self._user_sessions[session.user_id].add(new_access_token)

        return session

    def revoke_session(self, access_token: str) -> bool:
        """Revoke a session by access token."""
        session = self._sessions.get(access_token)
        if not session:
            return False

        self._revoke_access_token(access_token)
        return True

    def revoke_all_user_sessions(self, user_id: str) -> int:
        """Revoke all sessions for a user. Returns count of revoked sessions."""
        tokens = self._user_sessions.get(user_id, set())
        count = 0
        for token in tokens:
            if self._revoke_access_token(token):
                count += 1
        self._user_sessions[user_id] = set()
        return count

    def _revoke_access_token(self, access_token: str) -> bool:
        session = self._sessions.pop(access_token, None)
        if session:
            session.is_revoked = True
            self._refresh_index.pop(session.refresh_token, None)
            self._user_sessions.get(session.user_id, set()).discard(access_token)
            return True
        return False

    def touch_session(self, access_token: str) -> bool:
        """Update last_used_at for a session."""
        session = self._sessions.get(access_token)
        if session and session.is_valid():
            session.last_used_at = datetime.now()
            return True
        return False

    def cleanup_expired(self) -> int:
        """Remove expired sessions. Returns count of cleaned sessions."""
        now = datetime.now()
        expired_tokens = [
            token
            for token, session in self._sessions.items()
            if session.refresh_expires_at < now
        ]
        for token in expired_tokens:
            self._revoke_access_token(token)
        return len(expired_tokens)

    def get_user_session_count(self, user_id: str) -> int:
        """Get active session count for a user."""
        tokens = self._user_sessions.get(user_id, set())
        return sum(1 for t in tokens if (s := self._sessions.get(t)) and s.is_valid())


# Global session manager instance
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


def set_session_manager(manager: SessionManager) -> None:
    """Replace the global session manager (for testing)."""
    global _session_manager
    _session_manager = manager