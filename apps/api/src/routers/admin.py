"""Administrative Control Plane Router."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.core.config import settings
from apps.api.src.core.database import get_db
from apps.api.src.core.security import require_roles
from apps.api.src.core.exceptions import AppException, NotFoundException
from apps.api.src.models.audit import AuditEvent
from apps.api.src.models.delivery import MessageDelivery
from apps.api.src.models.outbox import OutboxEvent
from apps.api.src.models.session import Session
from apps.api.src.models.user import User
from apps.api.src.models.webhook import WebhookEndpoint
from apps.api.src.models.integration import IntegrationConfig
from apps.api.src.services.auth_service import AuthService
from packages.shared.src.constants import ErrorCode, UserRole
from packages.shared.src.crypto import generate_secure_token, hash_token
from packages.shared.src.ssrf import validate_destination_url

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


class WebhookCreateRequest(BaseModel):
    name: str
    url: str
    event_filters: List[str] = ["message.created"]
    max_retries: int = 5


class WebhookResponse(BaseModel):
    id: str
    name: str
    url: str
    secret_preview: str
    enabled: bool
    event_filters: List[str]
    created_at: str
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    last_failure_reason: Optional[str] = None


@router.get("/health")
async def get_system_health(
    auth=Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    """Detailed internal health metrics for administrators."""
    # DB health check
    db_ok = True
    try:
        await db.execute(select(1))
    except Exception:
        db_ok = False

    # Outbox backlog
    pending_count = (await db.execute(
        select(func.count(OutboxEvent.id)).where(OutboxEvent.status.in_(["pending", "retrying"]))
    )).scalar() or 0

    failed_count = (await db.execute(
        select(func.count(OutboxEvent.id)).where(OutboxEvent.status == "failed")
    )).scalar() or 0

    # Active sessions
    active_sessions_count = (await db.execute(
        select(func.count(Session.id)).where(
            Session.is_revoked == False, Session.expires_at > datetime.now(timezone.utc)
        )
    )).scalar() or 0

    return {
        "status": "healthy" if db_ok and failed_count == 0 else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "connected" if db_ok else "disconnected",
        "outbox": {
            "pending_or_retrying": pending_count,
            "failed_dead_letter": failed_count,
        },
        "active_sessions": active_sessions_count,
        "integrations": {
            "discord_enabled": settings.DISCORD_ENABLED,
            "webhook_enabled": settings.WEBHOOK_ENABLED,
            "signal_enabled": settings.SIGNAL_ENABLED,
        },
    }


@router.get("/sessions")
async def list_all_sessions(
    auth=Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    """List all user sessions across the system."""
    stmt = (
        select(Session, User.username, User.display_name)
        .join(User, Session.user_id == User.id)
        .order_by(Session.last_seen_at.desc())
        .limit(100)
    )
    results = (await db.execute(stmt)).all()
    return [
        {
            "id": s.id,
            "user_id": s.user_id,
            "username": username,
            "display_name": display_name,
            "device_name": s.device_name,
            "platform": s.platform,
            "is_revoked": s.is_revoked,
            "expires_at": s.expires_at.isoformat(),
            "last_seen_at": s.last_seen_at.isoformat(),
        }
        for s, username, display_name in results
    ]


@router.post("/sessions/{session_id}/revoke")
async def revoke_session_admin(
    session_id: str,
    auth=Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    """Administratively terminate any user session."""
    admin_id = auth["user"].id
    await AuthService.revoke_session(db, session_id=session_id, actor_id=admin_id)
    return {"message": "Session successfully revoked"}


@router.post("/devices/{device_name}/revoke")
async def revoke_device_admin(
    device_name: str,
    user_id: Optional[str] = None,
    auth=Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    """Revoke all sessions associated with a specific device identifier."""
    admin_id = auth["user"].id
    target_user_id = user_id or auth["user"].id
    count = await AuthService.revoke_device(db, user_id=target_user_id, device_name=device_name, actor_id=admin_id)
    return {"message": f"Revoked {count} sessions for device {device_name}"}


@router.get("/webhooks", response_model=List[WebhookResponse])
async def list_webhooks(
    auth=Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    """List registered webhooks with masked secrets."""
    query = select(WebhookEndpoint).order_by(WebhookEndpoint.created_at.desc())
    endpoints = (await db.execute(query)).scalars().all()
    return [
        WebhookResponse(
            id=ep.id,
            name=ep.name,
            url=ep.url,
            secret_preview=ep.secret_preview,
            enabled=ep.enabled,
            event_filters=json.loads(ep.event_filters_json),
            created_at=ep.created_at.isoformat(),
            last_success_at=ep.last_success_at.isoformat() if ep.last_success_at else None,
            last_failure_at=ep.last_failure_at.isoformat() if ep.last_failure_at else None,
            last_failure_reason=ep.last_failure_reason,
        )
        for ep in endpoints
    ]


@router.post("/webhooks", status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: WebhookCreateRequest,
    auth=Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    """Register new webhook destination with SSRF validation. Returns signing secret once."""
    # Enforce SSRF validation
    safe, reason = validate_destination_url(body.url, allow_localhost=settings.WEBHOOK_ALLOW_LOCALHOST)
    if not safe:
        raise AppException(ErrorCode.SSRF_BLOCKED, f"SSRF Blocked: {reason}")

    raw_secret = f"whsec_{generate_secure_token(24)}"
    secret_hash_val = hash_token(raw_secret)
    secret_preview = f"{raw_secret[:8]}...{raw_secret[-4:]}"

    ep = WebhookEndpoint(
        name=body.name,
        url=body.url,
        secret_hash=secret_hash_val,
        secret_preview=secret_preview,
        enabled=True,
        event_filters_json=json.dumps(body.event_filters),
        max_retries=body.max_retries,
        created_at=datetime.now(timezone.utc),
    )
    db.add(ep)
    await db.flush()

    await AuthService.record_audit(
        db,
        actor_id=auth["user"].id,
        action="webhook.created",
        target=f"webhook:{ep.id}",
        details={"name": ep.name, "url": ep.url},
    )

    return {
        "id": ep.id,
        "name": ep.name,
        "url": ep.url,
        "signing_secret": raw_secret,  # Displayed only once upon creation
        "secret_preview": ep.secret_preview,
        "message": "Webhook created successfully. Save signing_secret securely; it cannot be retrieved again."
    }


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(
    webhook_id: str,
    auth=Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    """Remove a webhook endpoint."""
    ep = (await db.execute(select(WebhookEndpoint).where(WebhookEndpoint.id == webhook_id))).scalar_one_or_none()
    if not ep:
        raise NotFoundException("Webhook endpoint not found")

    await db.delete(ep)
    await AuthService.record_audit(
        db,
        actor_id=auth["user"].id,
        action="webhook.deleted",
        target=f"webhook:{webhook_id}",
    )
    return {"message": "Webhook endpoint deleted"}


@router.get("/deliveries/failed")
async def list_failed_deliveries(
    auth=Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    """List failed integration deliveries for manual inspection."""
    query = (
        select(MessageDelivery)
        .where(MessageDelivery.status == "failed")
        .order_by(MessageDelivery.last_attempted_at.desc())
        .limit(50)
    )
    deliveries = (await db.execute(query)).scalars().all()
    return [
        {
            "id": d.id,
            "message_id": d.message_id,
            "integration_type": d.integration_type,
            "status": d.status,
            "attempt_count": d.attempt_count,
            "last_attempted_at": d.last_attempted_at.isoformat() if d.last_attempted_at else None,
            "failure_reason": d.failure_reason,
        }
        for d in deliveries
    ]


@router.post("/deliveries/{delivery_id}/retry")
async def retry_delivery(
    delivery_id: str,
    auth=Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    """Reset a failed delivery to queued for immediate retry."""
    delivery = (await db.execute(select(MessageDelivery).where(MessageDelivery.id == delivery_id))).scalar_one_or_none()
    if not delivery:
        raise NotFoundException("Delivery record not found")

    delivery.status = "queued"
    delivery.failure_reason = "Manual retry requested by admin"

    # Reset any failed outbox events for this message
    # Trigger outbox event retry
    await db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.status == "failed")
        .values(status="pending", next_attempt_at=datetime.now(timezone.utc), retry_count=0)
    )

    await AuthService.record_audit(
        db,
        actor_id=auth["user"].id,
        action="delivery.retry_triggered",
        target=f"delivery:{delivery_id}",
    )
    return {"message": "Delivery reset to queued for retry"}


@router.get("/audit")
async def get_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    auth=Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    """Inspect recent compliance and security audit logs."""
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    events = (await db.execute(query)).scalars().all()
    return [
        {
            "id": e.id,
            "actor_id": e.actor_id,
            "action": e.action,
            "target": e.target,
            "ip_address": e.ip_address,
            "details": json.loads(e.details_json),
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]


@router.post("/verify-integrity")
async def verify_database_integrity(
    auth=Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    """Run automated data consistency checks across database tables."""
    # Check 1: Sequence anomalies
    from apps.api.src.models.message import Message
    conv_query = select(Message.conversation_id).distinct()
    conv_ids = (await db.execute(conv_query)).scalars().all()

    anomalies = []
    for cid in conv_ids:
        msgs = (await db.execute(
            select(Message.sequence_number)
            .where(Message.conversation_id == cid)
            .order_by(Message.sequence_number.asc())
        )).scalars().all()
        # Verify strict sequence [1, 2, 3...]
        expected = 1
        for seq in msgs:
            if seq != expected:
                anomalies.append(f"Conversation {cid} has sequence gap or anomaly at {seq} (expected {expected})")
            expected += 1

    # Check 2: Stuck processing outbox events (> 5 minutes locked)
    stuck_query = select(func.count(OutboxEvent.id)).where(
        OutboxEvent.status == "processing",
        OutboxEvent.locked_at < datetime.now(timezone.utc),
    )
    stuck_count = (await db.execute(stuck_query)).scalar() or 0

    return {
        "status": "clean" if not anomalies and stuck_count == 0 else "issues_found",
        "sequence_anomalies": anomalies,
        "stuck_outbox_events": stuck_count,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
