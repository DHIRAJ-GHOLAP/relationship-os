"""Integration tests for Outbox Event Worker, retry logic, and dead lettering."""

import json
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from apps.api.src.models.outbox import OutboxEvent
from apps.api.src.models.delivery import MessageDelivery
from apps.api.src.services.outbox_worker import OutboxWorker, IntegrationRouter
from packages.shared.src.constants import DeliveryState, EventType, UserRole
from packages.shared.src.models import CanonicalMessageEvent, MessagePayload


class MockIntegrationRouter(IntegrationRouter):
    """Mock router allowing controllable delivery outcomes."""
    def __init__(self, outcomes=None):
        super().__init__()
        self.outcomes = outcomes or []

    async def route_event(self, db, event):
        results = []
        for outcome in self.outcomes:
            success = outcome.get("success", True)
            integration = outcome.get("integration", "discord")
            ext_id = outcome.get("external_id", "ext-001") if success else None
            err = outcome.get("error", None) if not success else None

            results.append({
                "integration": integration,
                "success": success,
                "external_id": ext_id,
                "error": err,
            })
            await self._update_delivery(db, event.message_id, integration, success, ext_id, err)
        return results


@pytest.mark.asyncio
async def test_outbox_worker_processes_pending_event_success(db_session, test_users):
    """Test successful outbox event drain transitions status to delivered."""
    conv = test_users["conversation"]
    owner = test_users["owner"]

    canonical_evt = CanonicalMessageEvent(
        event_id="evt-test-1",
        event_type=EventType.MESSAGE_CREATED,
        message_id="msg-test-1",
        conversation_id=conv.id,
        sender_id=owner.id,
        sender_name="Owner Alice",
        sender_role=UserRole.OWNER,
        sequence=1,
        origin="chat",
        message=MessagePayload(body="Hello outbox world"),
        timestamp=datetime.now(timezone.utc),
    )

    outbox_evt = OutboxEvent(
        id="evt-test-1",
        event_type=EventType.MESSAGE_CREATED.value,
        payload_json=canonical_evt.model_dump_json(),
        status="pending",
        retry_count=0,
        max_retries=3,
        next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db_session.add(outbox_evt)
    await db_session.commit()

    mock_router = MockIntegrationRouter([
        {"integration": "discord", "success": True, "external_id": "disc-ok-123"}
    ])
    worker = OutboxWorker(router=mock_router)

    processed = await worker.process_batch(batch_size=10)
    assert processed == 1

    db_session.expire_all()
    # Verify event state in DB
    updated_evt = (await db_session.execute(
        select(OutboxEvent).where(OutboxEvent.id == "evt-test-1")
    )).scalar_one()

    assert updated_evt.status == "delivered"
    assert updated_evt.completed_at is not None
    assert updated_evt.error_message is None

    # Verify delivery record
    delivery = (await db_session.execute(
        select(MessageDelivery).where(
            MessageDelivery.message_id == "msg-test-1",
            MessageDelivery.integration_type == "discord",
        )
    )).scalar_one_or_none()
    assert delivery is not None
    assert delivery.status == DeliveryState.DELIVERED.value
    assert delivery.external_message_id == "disc-ok-123"


@pytest.mark.asyncio
async def test_outbox_worker_retry_backoff_on_failure(db_session, test_users):
    """Test that failed delivery increments retry count and sets backoff."""
    conv = test_users["conversation"]
    owner = test_users["owner"]

    canonical_evt = CanonicalMessageEvent(
        event_id="evt-test-2",
        event_type=EventType.MESSAGE_CREATED,
        message_id="msg-test-2",
        conversation_id=conv.id,
        sender_id=owner.id,
        sender_name="Owner Alice",
        sender_role=UserRole.OWNER,
        sequence=2,
        origin="chat",
        message=MessagePayload(body="Retry message"),
        timestamp=datetime.now(timezone.utc),
    )

    outbox_evt = OutboxEvent(
        id="evt-test-2",
        event_type=EventType.MESSAGE_CREATED.value,
        payload_json=canonical_evt.model_dump_json(),
        status="pending",
        retry_count=0,
        max_retries=3,
        next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db_session.add(outbox_evt)
    await db_session.commit()

    mock_router = MockIntegrationRouter([
        {"integration": "discord", "success": False, "error": "503 Service Unavailable"}
    ])
    worker = OutboxWorker(router=mock_router)

    processed = await worker.process_batch(batch_size=10)
    assert processed == 1

    db_session.expire_all()
    updated_evt = (await db_session.execute(
        select(OutboxEvent).where(OutboxEvent.id == "evt-test-2")
    )).scalar_one()

    assert updated_evt.status == "retrying"
    assert updated_evt.retry_count == 1
    assert "503 Service Unavailable" in updated_evt.error_message
    from packages.shared.src.utils import ensure_utc
    assert ensure_utc(updated_evt.next_attempt_at) > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_outbox_worker_dead_letter_on_max_retries_exceeded(db_session, test_users):
    """Test that event exceeding max_retries is transitioned to dead-letter (failed)."""
    conv = test_users["conversation"]
    owner = test_users["owner"]

    canonical_evt = CanonicalMessageEvent(
        event_id="evt-test-3",
        event_type=EventType.MESSAGE_CREATED,
        message_id="msg-test-3",
        conversation_id=conv.id,
        sender_id=owner.id,
        sender_name="Owner Alice",
        sender_role=UserRole.OWNER,
        sequence=3,
        origin="chat",
        message=MessagePayload(body="Permanent failure message"),
        timestamp=datetime.now(timezone.utc),
    )

    outbox_evt = OutboxEvent(
        id="evt-test-3",
        event_type=EventType.MESSAGE_CREATED.value,
        payload_json=canonical_evt.model_dump_json(),
        status="retrying",
        retry_count=2,  # Already attempted twice
        max_retries=3,
        next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db_session.add(outbox_evt)
    await db_session.commit()

    mock_router = MockIntegrationRouter([
        {"integration": "discord", "success": False, "error": "400 Bad Request (Fatal)"}
    ])
    worker = OutboxWorker(router=mock_router)

    processed = await worker.process_batch(batch_size=10)
    assert processed == 1

    db_session.expire_all()
    updated_evt = (await db_session.execute(
        select(OutboxEvent).where(OutboxEvent.id == "evt-test-3")
    )).scalar_one()

    assert updated_evt.status == "failed"  # Dead letter state
    assert updated_evt.retry_count == 3
    assert "400 Bad Request" in updated_evt.error_message
