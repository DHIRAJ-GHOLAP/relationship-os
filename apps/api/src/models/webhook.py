"""Webhook endpoint entity model."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.src.core.database import Base


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # Masked, never returned plaintext
    secret_preview: Mapped[str] = mapped_column(String(16), nullable=False)  # e.g. "whsec_...abcd"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    event_filters_json: Mapped[str] = mapped_column(Text, default='["message.created"]', nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_success_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_reason: Mapped[str] = mapped_column(Text, nullable=True)
