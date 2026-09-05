"""Authentication and Session Management Router."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.core.config import settings
from apps.api.src.core.database import get_db
from apps.api.src.core.security import (
    create_access_token,
    get_current_user_and_session,
    require_roles,
)
from apps.api.src.models.session import Session
from apps.api.src.models.user import User
from apps.api.src.services.auth_service import AuthService
from packages.shared.src.constants import UserRole
from packages.shared.src.models import EnrollmentTokenCreate, EnrollmentTokenResponse, TokenResponse, UserBase

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str
    password: str
    device_name: str = "Web Browser"
    platform: str = "browser"


class EnrollRequest(BaseModel):
    token: str
    device_name: str = "Terminal Client"
    platform: str = "linux"


class SessionResponse(BaseModel):
    id: str
    device_name: str
    platform: str
    is_revoked: bool
    created_at: str
    last_seen_at: str


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user with username and password, return JWT and set HttpOnly cookie."""
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    user = await AuthService.authenticate_user(
        db,
        username=body.username,
        password=body.password,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    session, _ = await AuthService.create_session(
        db,
        user=user,
        device_name=body.device_name,
        platform=body.platform,
    )

    access_token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        session_id=session.id,
        device_name=body.device_name,
    )

    # Set secure HttpOnly cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserBase(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        ),
    )


@router.post("/enroll", response_model=TokenResponse)
async def enroll(
    request: Request,
    response: Response,
    body: EnrollRequest,
    db: AsyncSession = Depends(get_db),
):
    """Redeem a one-time enrollment token to bootstrap CLI or new device session."""
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    user, session, _ = await AuthService.redeem_enrollment_token(
        db,
        raw_token=body.token,
        device_name=body.device_name,
        platform=body.platform,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    access_token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        session_id=session.id,
        device_name=body.device_name,
    )

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserBase(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        ),
    )


@router.post("/enrollment-tokens", response_model=EnrollmentTokenResponse)
async def create_enrollment_token(
    body: EnrollmentTokenCreate,
    auth=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Generate high-entropy enrollment token for recipient (Owner/Admin only)."""
    # Find recipient user
    recip_query = await db.execute(select(User).where(User.role == UserRole.RECIPIENT))
    recipient = recip_query.scalar_one_or_none()
    if not recipient:
        recipient = auth["user"]

    token_str = await AuthService.create_enrollment_token(
        db,
        user_id=recipient.id,
        device_name=body.device_name,
        platform=body.platform,
        expires_hours=body.expires_in_hours,
    )

    from datetime import datetime, timedelta, timezone
    return EnrollmentTokenResponse(
        token=token_str,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=body.expires_in_hours),
        device_name=body.device_name,
    )


@router.get("/me", response_model=UserBase)
async def get_me(auth=Depends(get_current_user_and_session)):
    """Return currently authenticated user information."""
    user = auth["user"]
    return UserBase(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.get("/sessions", response_model=List[SessionResponse])
async def list_user_sessions(
    auth=Depends(get_current_user_and_session),
    db: AsyncSession = Depends(get_db),
):
    """List all active sessions for current user."""
    user = auth["user"]
    query = (
        select(Session)
        .where(Session.user_id == user.id, Session.is_revoked == False)
        .order_by(Session.last_seen_at.desc())
    )
    sessions = (await db.execute(query)).scalars().all()
    return [
        SessionResponse(
            id=s.id,
            device_name=s.device_name,
            platform=s.platform,
            is_revoked=s.is_revoked,
            created_at=s.created_at.isoformat(),
            last_seen_at=s.last_seen_at.isoformat(),
        )
        for s in sessions
    ]


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    auth=Depends(get_current_user_and_session),
    db: AsyncSession = Depends(get_db),
):
    """Invalidate current session and clear authentication cookies."""
    session = auth["session"]
    user = auth["user"]
    client_ip = request.client.host if request.client else None

    await AuthService.revoke_session(
        db, session_id=session.id, actor_id=user.id, ip_address=client_ip
    )
    await db.commit()
    response.delete_cookie("access_token")
    return {"message": "Logged out successfully"}
