"""System health, readiness, liveness, and privacy-safe metrics."""

import time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.core.config import settings
from apps.api.src.core.database import get_db
from apps.api.src.models.message import Message
from apps.api.src.models.outbox import OutboxEvent
from apps.api.src.models.session import Session

router = APIRouter(tags=["Health"])

START_TIME = time.time()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """General health check."""
    try:
        await db.execute(select(1))
        db_status = "healthy"
    except Exception:
        db_status = "unhealthy"

    return {
        "status": "ok" if db_status == "healthy" else "degraded",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "database": db_status,
        "uptime_seconds": int(time.time() - START_TIME),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/live")
async def liveness():
    """Liveness probe indicating application process is running."""
    return {"status": "alive"}


@router.get("/ready")
async def readiness(response: Response, db: AsyncSession = Depends(get_db)):
    """Readiness probe indicating application is ready to accept traffic."""
    try:
        await db.execute(select(1))
        return {"status": "ready"}
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "reason": "Database connection failed"}


@router.get("/metrics")
async def privacy_safe_metrics(db: AsyncSession = Depends(get_db)):
    """
    Privacy-safe system performance and throughput metrics.
    Strictly excludes all message bodies, secrets, or participant identifiers.
    """
    msg_count = (await db.execute(select(func.count(Message.id)))).scalar() or 0
    pending_outbox = (await db.execute(
        select(func.count(OutboxEvent.id)).where(OutboxEvent.status == "pending")
    )).scalar() or 0
    active_sessions = (await db.execute(
        select(func.count(Session.id)).where(
            Session.is_revoked == False, Session.expires_at > datetime.now(timezone.utc)
        )
    )).scalar() or 0

    return {
        "uptime_seconds": int(time.time() - START_TIME),
        "total_messages_persisted": msg_count,
        "outbox_pending_count": pending_outbox,
        "active_sessions_count": active_sessions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
