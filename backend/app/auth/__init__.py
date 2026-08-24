"""Authentication and user management."""

from __future__ import annotations

from .models import User, UserCreate, UserInDB
from .password import hash_password, verify_password
from .session import SessionManager, get_session_manager
from .dependencies import get_current_user, get_current_user_optional, require_user

__all__ = [
    "User",
    "UserCreate",
    "UserInDB",
    "hash_password",
    "verify_password",
    "SessionManager",
    "get_session_manager",
    "get_current_user",
    "get_current_user_optional",
    "require_user",
]