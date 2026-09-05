"""Presence tracking service with heartbeat and automatic stale expiration."""

from datetime import datetime, timedelta, timezone
from typing import Dict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.models.presence import UserPresence
from packages.shared.src.constants import PresenceState
from packages.shared.src.utils import ensure_utc

HEARTBEAT_TIMEOUT_SECONDS = 60


class PresenceService:
    @staticmethod
    async def update_presence(
        db: AsyncSession,
        user_id: str,
        status: PresenceState,
        device_name: str = "",
    ) -> UserPresence:
        stmt = select(UserPresence).where(UserPresence.user_id == user_id)
        presence = (await db.execute(stmt)).scalar_one_or_none()

        status_val = status.value if hasattr(status, "value") else str(status)

        if not presence:
            presence = UserPresence(
                user_id=user_id,
                status=status_val,
                device_name=device_name,
                last_heartbeat_at=datetime.now(timezone.utc),
            )
            db.add(presence)
        else:
            presence.status = status_val
            presence.device_name = device_name
            presence.last_heartbeat_at = datetime.now(timezone.utc)

        await db.flush()
        return presence

    @staticmethod
    async def get_user_presence(db: AsyncSession, user_id: str) -> Dict[str, str]:
        stmt = select(UserPresence).where(UserPresence.user_id == user_id)
        presence = (await db.execute(stmt)).scalar_one_or_none()

        if not presence:
            return {"status": PresenceState.OFFLINE.value, "device_name": ""}

        stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)
        if ensure_utc(presence.last_heartbeat_at) < stale_cutoff and presence.status != PresenceState.OFFLINE.value:
            presence.status = PresenceState.OFFLINE.value
            await db.flush()

        return {"status": presence.status, "device_name": presence.device_name}

    @staticmethod
    async def expire_stale_sessions(db: AsyncSession, timeout_seconds: int = 60) -> int:
        stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        stmt = (
            update(UserPresence)
            .where(UserPresence.last_heartbeat_at < stale_cutoff, UserPresence.status != PresenceState.OFFLINE.value)
            .values(status=PresenceState.OFFLINE.value)
        )
        res = await db.execute(stmt)
        return res.rowcount
