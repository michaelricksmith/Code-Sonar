"""Authentication API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth.dependencies import (
    _get_user_by_email,
    _save_user,
    get_current_user,
    get_session_manager,
)
from app.auth.models import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    TokenPair,
    User,
    UserCreate,
    UserInDB,
    UserLogin,
)
from app.auth.password import hash_password, verify_password
from app.auth.session import SessionManager

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterResponse(BaseModel):
    user: User
    tokens: TokenPair


class LoginResponse(BaseModel):
    user: User
    tokens: TokenPair


class MeResponse(BaseModel):
    user: User


class MessageResponse(BaseModel):
    message: str


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_create: UserCreate,
    request: Request,
    session_manager: SessionManager = Depends(get_session_manager),
) -> RegisterResponse:
    """Register a new user account."""
    # Validate passwords match
    if not user_create.passwords_match():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match",
        )

    # Check if email already exists
    existing = _get_user_by_email(user_create.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Hash password and create user
    password_hash = hash_password(user_create.password)
    user_in_db = UserInDB.create(user_create, password_hash)
    _save_user(user_in_db)

    # Create session
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None
    session = session_manager.create_session(user_in_db, user_agent, ip_address)

    tokens = TokenPair(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=3600,
    )

    return RegisterResponse(user=user_in_db.to_public(), tokens=tokens)


@router.post("/login", response_model=LoginResponse)
async def login(
    credentials: UserLogin,
    request: Request,
    response: Response,
    session_manager: SessionManager = Depends(get_session_manager),
) -> LoginResponse:
    """Authenticate user and create session."""
    user = _get_user_by_email(credentials.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    # Update last login
    user.last_login_at = user.created_at.__class__.now()
    _save_user(user)

    # Create session
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None
    session = session_manager.create_session(user, user_agent, ip_address)

    tokens = TokenPair(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=3600,
    )

    return LoginResponse(user=user.to_public(), tokens=tokens)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    credentials: UserLogin | None = None,  # Not used but keeps signature consistent
    current_user: User = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
) -> MessageResponse:
    """Log out the current user (revoke current session)."""
    # The get_current_user dependency already validated the token
    # We need to extract the token from the request to revoke it
    # This is handled by the dependency, but we need access to the token
    # For simplicity, we revoke all user sessions on logout
    session_manager.revoke_all_user_sessions(current_user.id)
    return MessageResponse(message="Logged out successfully")


@router.post("/logout-all", response_model=MessageResponse)
async def logout_all(
    current_user: User = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
) -> MessageResponse:
    """Log out from all devices (revoke all sessions)."""
    session_manager.revoke_all_user_sessions(current_user.id)
    return MessageResponse(message="Logged out from all devices")


@router.post("/refresh", response_model=TokenPair)
async def refresh_token(
    refresh_request: "RefreshRequest",
    session_manager: SessionManager = Depends(get_session_manager),
) -> TokenPair:
    """Refresh access token using refresh token."""
    from app.auth.models import RefreshRequest

    session = session_manager.refresh_access_token(refresh_request.refresh_token)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    return TokenPair(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=3600,
    )


@router.get("/me", response_model=MeResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> MeResponse:
    """Get current authenticated user profile."""
    return MeResponse(user=current_user)


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    request: ForgotPasswordRequest,
) -> MessageResponse:
    """Initiate password reset (placeholder - sends email in production)."""
    user = _get_user_by_email(request.email)
    # Always return success to prevent email enumeration
    # In production, send reset email with token
    return MessageResponse(
        message="If the email exists, a password reset link has been sent"
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    request: ResetPasswordRequest,
) -> MessageResponse:
    """Complete password reset (placeholder - validates token in production)."""
    if not request.passwords_match():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match",
        )
    # In production, validate reset token and update password
    return MessageResponse(message="Password has been reset")


# Import here to avoid circular dependency
from app.auth.models import RefreshRequest  # noqa: E402