"""Auth models: user schemas and database representations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """Request payload for user registration."""

    name: str = Field(min_length=1, max_length=100, description="Display name")
    email: EmailStr = Field(description="Email address")
    password: str = Field(min_length=8, max_length=128, description="Plaintext password")
    confirm_password: str = Field(description="Password confirmation")
    invite_code: str | None = Field(default=None, description="Optional private-beta invite code")

    def passwords_match(self) -> bool:
        return self.password == self.confirm_password


class User(BaseModel):
    """Public user representation (safe for API responses)."""

    id: str
    name: str
    email: EmailStr
    created_at: datetime
    last_login_at: datetime | None = None
    is_active: bool = True

    @classmethod
    def from_db(cls, user_in_db: "UserInDB") -> "User":
        return cls(
            id=user_in_db.id,
            name=user_in_db.name,
            email=user_in_db.email,
            created_at=user_in_db.created_at,
            last_login_at=user_in_db.last_login_at,
            is_active=user_in_db.is_active,
        )


@dataclass
class UserInDB:
    """Internal user representation with password hash."""

    id: str
    name: str
    email: str
    password_hash: str
    created_at: datetime
    last_login_at: datetime | None = None
    is_active: bool = True

    @classmethod
    def create(cls, user_create: UserCreate, password_hash: str) -> "UserInDB":
        now = datetime.now()
        return cls(
            id=str(uuid4()),
            name=user_create.name.strip(),
            email=user_create.email.lower(),
            password_hash=password_hash,
            created_at=now,
            last_login_at=None,
            is_active=True,
        )

    def to_public(self) -> User:
        return User.from_db(self)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for database storage."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "password_hash": self.password_hash,
            "created_at": self.created_at.isoformat(),
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserInDB":
        return cls(
            id=data["id"],
            name=data["name"],
            email=data["email"],
            password_hash=data["password_hash"],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_login_at=datetime.fromisoformat(data["last_login_at"]) if data.get("last_login_at") else None,
            is_active=data.get("is_active", True),
        )


class UserLogin(BaseModel):
    """Request payload for user login."""

    email: EmailStr
    password: str


class TokenPair(BaseModel):
    """Access + refresh token pair."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600  # seconds


class RefreshRequest(BaseModel):
    """Request to refresh access token."""

    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    """Request to initiate password reset."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Request to complete password reset."""

    token: str
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str

    def passwords_match(self) -> bool:
        return self.password == self.confirm_password