"""Authentication, user management, session management, and audit logging service."""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.core.config import settings
from apps.api.src.core.exceptions import (
    AuthExpiredException,
    AuthInvalidException,
    ForbiddenException,
    NotFoundException,
)
from apps.api.src.models.user import User
from apps.api.src.models.session import Session
from apps.api.src.models.enrollment import EnrollmentToken
from apps.api.src.models.audit import AuditEvent
from packages.shared.src.constants import UserRole
from packages.shared.src.crypto import (
    generate_secure_token,
    hash_password,
    hash_token,
    verify_password,
)
from packages.shared.src.utils import ensure_utc


class AuthService:
    @staticmethod
    async def create_user(
        db: AsyncSession,
        username: str,
        display_name: str,
        password: str,
        role: UserRole = UserRole.RECIPIENT,
    ) -> User:
        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            raise ForbiddenException(f"User with username '{username}' already exists")

        user = User(
            username=username,
            display_name=display_name,
            hashed_password=hash_password(password),
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        return user

    @staticmethod
    async def authenticate_user(
        db: AsyncSession,
        username: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> User:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            await AuthService.record_audit(
                db,
                actor_id=username or "anonymous",
                action="auth.login_failed",
                target="user",
                ip=ip_address,
                ua=user_agent,
                details={"reason": "User not found or inactive"},
            )
            raise AuthInvalidException("Invalid username or password")

        if not verify_password(password, user.hashed_password):
            await AuthService.record_audit(
                db,
                actor_id=str(user.id),
                action="auth.login_failed",
                target=f"user:{user.id}",
                ip=ip_address,
                ua=user_agent,
                details={"reason": "Password mismatch"},
            )
            raise AuthInvalidException("Invalid username or password")

        await AuthService.record_audit(
            db,
            actor_id=str(user.id),
            action="auth.login_success",
            target=f"user:{user.id}",
            ip=ip_address,
            ua=user_agent,
        )
        return user

    @staticmethod
    async def create_session(
        db: AsyncSession,
        user: User,
        device_name: str = "Web Client",
        platform: str = "browser",
    ) -> Tuple[Session, str]:
        raw_token = generate_secure_token(32)
        token_hash = hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

        session = Session(
            user_id=user.id,
            device_name=device_name,
            platform=platform,
            token_hash=token_hash,
            is_revoked=False,
            expires_at=expires_at,
            last_seen_at=datetime.now(timezone.utc),
        )
        db.add(session)
        await db.flush()
        return session, raw_token

    @staticmethod
    async def create_enrollment_token(
        db: AsyncSession,
        user_id: str,
        device_name: str = "Terminal Client",
        platform: str = "windows",
        expires_hours: int = 24,
    ) -> str:
        raw_token = generate_secure_token(32)
        token_hash = hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)

        enrollment = EnrollmentToken(
            token_hash=token_hash,
            user_id=user_id,
            device_name=device_name,
            platform=platform,
            is_used=False,
            is_revoked=False,
            expires_at=expires_at,
        )
        db.add(enrollment)
        await db.flush()

        await AuthService.record_audit(
            db,
            actor_id=user_id,
            action="enrollment.created",
            target=f"user:{user_id}",
            details={"device_name": device_name, "platform": platform, "expires_hours": expires_hours},
        )
        return raw_token

    @staticmethod
    async def redeem_enrollment_token(
        db: AsyncSession,
        raw_token: str,
        device_name: Optional[str] = None,
        platform: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[User, Session, str]:
        token_hash = hash_token(raw_token)
        query = await db.execute(
            select(EnrollmentToken).where(EnrollmentToken.token_hash == token_hash)
        )
        enrollment = query.scalar_one_or_none()

        if not enrollment:
            await AuthService.record_audit(
                db,
                actor_id="anonymous",
                action="enrollment.redeem_failed",
                target="enrollment_token",
                ip=ip_address,
                ua=user_agent,
                details={"reason": "Token not found"},
            )
            raise AuthInvalidException("Enrollment token is invalid")

        if enrollment.is_revoked:
            await AuthService.record_audit(
                db,
                actor_id=str(enrollment.user_id),
                action="enrollment.redeem_failed",
                target=f"enrollment:{enrollment.id}",
                ip=ip_address,
                ua=user_agent,
                details={"reason": "Token revoked"},
            )
            raise AuthInvalidException("Enrollment token has been revoked")

        if enrollment.is_used:
            await AuthService.record_audit(
                db,
                actor_id=str(enrollment.user_id),
                action="enrollment.redeem_failed",
                target=f"enrollment:{enrollment.id}",
                ip=ip_address,
                ua=user_agent,
                details={"reason": "Token already used"},
            )
            raise AuthInvalidException("Enrollment token has already been redeemed")

        if ensure_utc(enrollment.expires_at) < datetime.now(timezone.utc):
            await AuthService.record_audit(
                db,
                actor_id=str(enrollment.user_id),
                action="enrollment.redeem_failed",
                target=f"enrollment:{enrollment.id}",
                ip=ip_address,
                ua=user_agent,
                details={"reason": "Token expired"},
            )
            raise AuthExpiredException("Enrollment token has expired")

        enrollment.is_used = True

        user_query = await db.execute(select(User).where(User.id == enrollment.user_id))
        user = user_query.scalar_one_or_none()
        if not user or not user.is_active:
            raise AuthInvalidException("User account associated with this token is disabled")

        actual_device = device_name or enrollment.device_name
        actual_platform = platform or enrollment.platform

        session, session_raw_token = await AuthService.create_session(
            db, user=user, device_name=actual_device, platform=actual_platform
        )

        await AuthService.record_audit(
            db,
            actor_id=str(user.id),
            action="enrollment.redeem_success",
            target=f"session:{session.id}",
            ip=ip_address,
            ua=user_agent,
            details={"device_name": actual_device, "platform": actual_platform},
        )

        return user, session, session_raw_token

    @staticmethod
    async def revoke_session(
        db: AsyncSession,
        session_id: str,
        actor_id: str,
        ip_address: Optional[str] = None,
    ) -> None:
        query = await db.execute(select(Session).where(Session.id == session_id))
        session = query.scalar_one_or_none()
        if not session:
            raise NotFoundException("Session not found")

        session.is_revoked = True
        await AuthService.record_audit(
            db,
            actor_id=actor_id,
            action="session.revoked",
            target=f"session:{session_id}",
            ip=ip_address,
            details={"user_id": str(session.user_id), "device_name": session.device_name},
        )
        await db.commit()

    @staticmethod
    async def revoke_device(
        db: AsyncSession,
        user_id: str,
        device_name: str,
        actor_id: str,
        ip_address: Optional[str] = None,
    ) -> int:
        stmt = (
            update(Session)
            .where(Session.user_id == user_id, Session.device_name == device_name, Session.is_revoked == False)
            .values(is_revoked=True)
        )
        result = await db.execute(stmt)
        count = result.rowcount

        await AuthService.record_audit(
            db,
            actor_id=actor_id,
            action="device.revoked",
            target=f"device:{device_name}",
            ip=ip_address,
            details={"user_id": user_id, "revoked_sessions_count": count},
        )
        return count

    @staticmethod
    async def record_audit(
        db: AsyncSession,
        actor_id: str,
        action: str,
        target: str,
        ip: Optional[str] = None,
        ua: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> AuditEvent:
        audit = AuditEvent(
            actor_id=str(actor_id),
            action=action,
            target=target,
            ip_address=ip,
            user_agent=ua[:255] if ua else None,
            details_json=json.dumps(details or {}),
            created_at=datetime.now(timezone.utc),
        )
        db.add(audit)
        return audit
