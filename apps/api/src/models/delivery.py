"""Message delivery tracking per integration."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.src.core.database import Base


class MessageDelivery(Base):
    __tablename__ = "message_deliveries"
    __table_args__ = (
        Index("ix_deliveries_msg_integration", "message_id", "integration_type"),
        Index("ix_deliveries_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_type: Mapped[str] = mapped_column(String(64), nullable=False)  # discord, webhook, signal
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)  # queued, processing, delivered, retrying, failed
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=True)
    external_message_id: Mapped[str] = mapped_column(String(255), nullable=True)

    message = relationship("Message", back_populates="deliveries")
