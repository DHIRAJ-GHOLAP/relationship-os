"""Canonical Pydantic models for Relationship OS."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from .constants import DeliveryState, ErrorCode, EventType, MessageType, PresenceState, UserRole


class APIErrorDetail(BaseModel):
    """Predictable API error format."""
    code: ErrorCode
    message: str
    request_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class UserBase(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    display_name: str
    role: UserRole
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserBase


class EnrollmentTokenCreate(BaseModel):
    device_name: str = "Terminal Client"
    platform: str = "linux"
    expires_in_hours: int = 24


class EnrollmentTokenResponse(BaseModel):
    token: str
    expires_at: datetime
    device_name: str


class MessagePayload(BaseModel):
    type: MessageType = MessageType.TEXT
    body: str
    attachments: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class MessageSendRequest(BaseModel):
    client_message_id: str
    message: MessagePayload


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    sender_name: Optional[str] = None
    message_type: MessageType
    body: str
    created_at: datetime
    edited_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    client_message_id: str
    sequence_number: int
    delivery_state: DeliveryState
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CanonicalMessageEvent(BaseModel):
    """The canonical event schema for all integrations and real-time clients."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType = EventType.MESSAGE_CREATED
    conversation_id: str
    message_id: str
    sender_id: str
    sender_role: Optional[UserRole] = None
    sender_name: Optional[str] = None
    sequence: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    origin: str = "chat"
    message: MessagePayload
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReadReceiptRequest(BaseModel):
    last_read_sequence: int


class PresenceUpdate(BaseModel):
    status: PresenceState
    device_name: Optional[str] = None
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WebSocketClientFrame(BaseModel):
    action: str  # "auth", "ping", "sync", "send", "read", "typing"
    payload: Dict[str, Any] = Field(default_factory=dict)


class WebSocketServerFrame(BaseModel):
    type: str  # "ack", "pong", "event", "replay", "presence", "error"
    event_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
