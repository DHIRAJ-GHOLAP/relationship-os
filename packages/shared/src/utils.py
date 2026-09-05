"""Time and utility helpers."""

from datetime import datetime, timezone


def ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime object is timezone-aware UTC."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
