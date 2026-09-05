"""Shared package for Relationship OS."""

from .constants import (
    UserRole,
    MessageType,
    DeliveryState,
    PresenceState,
    EventType,
    ErrorCode,
)
from .models import (
    APIErrorDetail,
    UserBase,
    TokenResponse,
    EnrollmentTokenCreate,
    EnrollmentTokenResponse,
    MessagePayload,
    MessageSendRequest,
    MessageResponse,
    CanonicalMessageEvent,
    ReadReceiptRequest,
    PresenceUpdate,
    WebSocketClientFrame,
    WebSocketServerFrame,
)
from .crypto import (
    hash_password,
    verify_password,
    generate_secure_token,
    hash_token,
    compute_webhook_signature,
    verify_webhook_signature,
)
from .ssrf import validate_destination_url

__all__ = [
    "UserRole",
    "MessageType",
    "DeliveryState",
    "PresenceState",
    "EventType",
    "ErrorCode",
    "APIErrorDetail",
    "UserBase",
    "TokenResponse",
    "EnrollmentTokenCreate",
    "EnrollmentTokenResponse",
    "MessagePayload",
    "MessageSendRequest",
    "MessageResponse",
    "CanonicalMessageEvent",
    "ReadReceiptRequest",
    "PresenceUpdate",
    "WebSocketClientFrame",
    "WebSocketServerFrame",
    "hash_password",
    "verify_password",
    "generate_secure_token",
    "hash_token",
    "compute_webhook_signature",
    "verify_webhook_signature",
    "validate_destination_url",
]
