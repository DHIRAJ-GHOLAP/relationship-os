"""Audit event entity model for centralized compliance and security auditing."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.src.core.database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_actor_action", "actor_id", "action"),
        Index("ix_audit_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)  # user ID or system
    action: Mapped[str] = mapped_column(String(64), nullable=False)  # auth.login, auth.failed, token.issued, etc.
    target: Mapped[str] = mapped_column(String(128), nullable=False)  # user, session, webhook, integration
    ip_address: Mapped[str] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str] = mapped_column(String(255), nullable=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)  # Non-sensitive details
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
