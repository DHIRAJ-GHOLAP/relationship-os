"""Authentication, authorization, and cryptographic token management."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_db
from .exceptions import AuthExpiredException, AuthInvalidException, ForbiddenException
from packages.shared.src.constants import UserRole
from packages.shared.src.crypto import hash_token
from packages.shared.src.utils import ensure_utc

security_scheme = HTTPBearer(auto_error=False)
ALGORITHM = "HS256"


def create_access_token(
    user_id: str,
    username: str,
    role: UserRole,
    session_id: str,
    device_name: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate a signed JWT access token."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode: Dict[str, Any] = {
        "sub": user_id,
        "username": username,
        "role": role.value if hasattr(role, "value") else str(role),
        "session_id": session_id,
        "device_name": device_name or "unknown",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(to_encode, settings.SESSION_SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(
            token,
            settings.SESSION_SECRET,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "role", "session_id"]}
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise AuthExpiredException("Token has expired")
    except jwt.InvalidTokenError:
        raise AuthInvalidException("Invalid token signature or claims")


async def get_current_user_and_session(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
):
    """
    Dependency to authenticate request and verify session has not been revoked.
    Checks Authorization: Bearer <token> or HttpOnly session cookie.
    """
    token = None
    if credentials:
        token = credentials.credentials
    elif "access_token" in request.cookies:
        token = request.cookies.get("access_token")

    if not token:
        raise AuthInvalidException("Authentication token is missing")

    payload = decode_access_token(token)
    user_id = payload.get("sub")
    session_id = payload.get("session_id")
    role_str = payload.get("role")

    if not user_id or not session_id:
        raise AuthInvalidException("Invalid token claims")

    # Verify session in database (ensures session is active and not revoked)
    from apps.api.src.models.session import Session
    from apps.api.src.models.user import User

    session_query = await db.execute(
        select(Session).where(Session.id == session_id, Session.is_revoked == False)
    )
    session = session_query.scalar_one_or_none()
    if not session:
        raise AuthInvalidException("Session has been revoked or does not exist")

    if ensure_utc(session.expires_at) < datetime.now(timezone.utc):
        raise AuthExpiredException("Session has expired")

    user_query = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = user_query.scalar_one_or_none()
    if not user:
        raise AuthInvalidException("User account not found or disabled")

    # Update session last_seen_at
    session.last_seen_at = datetime.now(timezone.utc)

    return {"user": user, "session": session, "role": user.role}


def require_roles(*allowed_roles: UserRole):
    """Factory dependency for role-based access control."""
    async def role_checker(auth=Depends(get_current_user_and_session)):
        user_role = auth["role"]
        if user_role == UserRole.ADMIN:
            return auth
        if user_role not in allowed_roles:
            raise ForbiddenException(f"Access denied for role {user_role}")
        return auth
    return role_checker
