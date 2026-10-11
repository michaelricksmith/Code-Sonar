"""Server-side sessions: short-lived access tokens + rotating refresh.

Copyright © 2026 Michael Smith. All rights reserved.

Access tokens are 15-minute JWTs carrying the session id. Refresh
tokens are opaque, single-use, and rotate on every use: the old hash is
replaced, so a stolen refresh token is dead after the legitimate client
refreshes once. Sessions are revocable individually or all at once.

Legacy stateless session JWTs (no ``sid`` claim) keep working until
they expire; new logins always create server-side sessions.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import jwt

ACCESS_TTL_SECONDS = 15 * 60
REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60


@dataclass
class UserSession:
    session_id: str
    user_id: str
    created_at: str
    expires_at: str
    last_seen_at: str | None = None
    device_info: str | None = None
    ip_address: str | None = None
    revoked: bool = False


class SessionStore(Protocol):
    def create(
        self,
        user_id: str,
        refresh_token_hash: str,
        *,
        device_info: str | None,
        ip_address: str | None,
    ) -> UserSession: ...
    def get(self, session_id: str) -> UserSession | None: ...
    def get_by_refresh_hash(self, refresh_token_hash: str) -> UserSession | None: ...
    def rotate_refresh(self, session_id: str, new_hash: str) -> bool: ...
    def touch(self, session_id: str) -> None: ...
    def revoke(self, session_id: str) -> bool: ...
    def revoke_all_for_user(self, user_id: str, except_session_id: str | None) -> int: ...
    def list_for_user(self, user_id: str) -> list[UserSession]: ...
    def get_refresh_hash(self, session_id: str) -> str | None: ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, UserSession] = {}
        self._refresh_hashes: dict[str, str] = {}

    def create(
        self,
        user_id: str,
        refresh_token_hash: str,
        *,
        device_info: str | None,
        ip_address: str | None,
    ) -> UserSession:
        now = datetime.now(timezone.utc)
        session = UserSession(
            session_id="sess_" + uuid.uuid4().hex[:24],
            user_id=user_id,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=REFRESH_TTL_SECONDS)).isoformat(),
            last_seen_at=now.isoformat(),
            device_info=device_info,
            ip_address=ip_address,
        )
        self._sessions[session.session_id] = session
        self._refresh_hashes[session.session_id] = refresh_token_hash
        return session

    def get(self, session_id: str) -> UserSession | None:
        return self._sessions.get(session_id)

    def get_by_refresh_hash(self, refresh_token_hash: str) -> UserSession | None:
        for sid, h in self._refresh_hashes.items():
            if hmac_compare(h, refresh_token_hash):
                return self._sessions.get(sid)
        return None

    def rotate_refresh(self, session_id: str, new_hash: str) -> bool:
        if session_id not in self._sessions:
            return False
        self._refresh_hashes[session_id] = new_hash
        return True

    def touch(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.last_seen_at = datetime.now(timezone.utc).isoformat()

    def revoke(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None or session.revoked:
            return False
        session.revoked = True
        self._refresh_hashes.pop(session_id, None)
        return True

    def revoke_all_for_user(self, user_id: str, except_session_id: str | None) -> int:
        count = 0
        for session in self._sessions.values():
            if session.user_id == user_id and not session.revoked:
                if except_session_id and session.session_id == except_session_id:
                    continue
                session.revoked = True
                self._refresh_hashes.pop(session.session_id, None)
                count += 1
        return count

    def list_for_user(self, user_id: str) -> list[UserSession]:
        return [s for s in self._sessions.values() if s.user_id == user_id]

    def get_refresh_hash(self, session_id: str) -> str | None:
        return self._refresh_hashes.get(session_id)


def hmac_compare(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a, b)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def new_access_token(session_id: str, user_id: str, secret: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": user_id, "sid": session_id, "iat": now,
         "exp": now + ACCESS_TTL_SECONDS},
        secret,
        algorithm="HS256",
    )


def decode_access_token(token: str, secret: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return dict(payload)


_store: SessionStore = InMemorySessionStore()


def get_session_store() -> SessionStore:
    return _store


def set_session_store(store: SessionStore) -> None:
    global _store
    _store = store
