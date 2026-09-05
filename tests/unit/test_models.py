"""Unit tests for Pydantic models, canonical schemas, and state transitions."""

import pytest
from packages.shared.src.constants import DeliveryState, EventType, MessageType, UserRole
from packages.shared.src.models import (
    CanonicalMessageEvent,
    MessagePayload,
    MessageResponse,
)


def test_canonical_message_event_serialization():
    payload = MessagePayload(type=MessageType.TEXT, body="Hello world")
    event = CanonicalMessageEvent(
        conversation_id="conv-123",
        message_id="msg-456",
        sender_id="user-789",
        sender_role=UserRole.OWNER,
        sequence=1,
        message=payload,
    )

    serialized = event.model_dump_json()
    assert "conv-123" in serialized
    assert "msg-456" in serialized
    assert "Hello world" in serialized
    assert "message.created" in serialized

    # Deserialize back
    restored = CanonicalMessageEvent.model_validate_json(serialized)
    assert restored.conversation_id == "conv-123"
    assert restored.sequence == 1
    assert restored.sender_role == UserRole.OWNER
    assert restored.message.body == "Hello world"


def test_delivery_state_enums():
    valid_states = [s.value for s in DeliveryState]
    assert "queued" in valid_states
    assert "processing" in valid_states
    assert "delivered" in valid_states
    assert "failed" in valid_states
    assert "retrying" in valid_states
