"""Canonical constants for Relationship OS."""

from enum import Enum


class UserRole(str, Enum):
    """User authorization roles."""
    OWNER = "OWNER"
    RECIPIENT = "RECIPIENT"
    ADMIN = "ADMIN"


class MessageType(str, Enum):
    """Supported canonical message types."""
    TEXT = "text"
    SYSTEM = "system"
    MEDIA = "media"
    FILE = "file"
    EVENT = "event"
    REACTION = "reaction"


class DeliveryState(str, Enum):
    """Legal delivery states in the state machine."""
    STORED = "stored"
    QUEUED = "queued"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    READ = "read"


class PresenceState(str, Enum):
    """Presence status."""
    ONLINE = "online"
    AWAY = "away"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class EventType(str, Enum):
    """Canonical event types for WebSocket and Outbox distribution."""
    MESSAGE_CREATED = "message.created"
    MESSAGE_DELIVERED = "message.delivered"
    MESSAGE_READ = "message.read"
    PRESENCE_UPDATED = "presence.updated"
    TYPING_STARTED = "typing.started"
    TYPING_STOPPED = "typing.stopped"
    SESSION_REVOKED = "session.revoked"


class ErrorCode(str, Enum):
    """Stable, machine-readable error codes."""
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_INVALID = "AUTH_INVALID"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    MESSAGE_TOO_LARGE = "MESSAGE_TOO_LARGE"
    MESSAGE_DUPLICATE = "MESSAGE_DUPLICATE"
    RATE_LIMITED = "RATE_LIMITED"
    INVALID_REQUEST = "INVALID_REQUEST"
    INTEGRATION_UNAVAILABLE = "INTEGRATION_UNAVAILABLE"
    SSRF_BLOCKED = "SSRF_BLOCKED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
