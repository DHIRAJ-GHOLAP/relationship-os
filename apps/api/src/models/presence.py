"""Presence tracking entity."""

from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.src.core.database import Base


class UserPresence(Base):
    __tablename__ = "user_presences"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="offline", nullable=False)  # online, away, offline
    device_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
