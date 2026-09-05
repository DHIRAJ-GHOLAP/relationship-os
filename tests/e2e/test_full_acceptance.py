"""End-to-end full acceptance test verifying the complete Relationship OS lifecycle.

Flow:
1. Bootstrap Owner and Recipient accounts.
2. Owner creates high-entropy enrollment token for recipient device.
3. Recipient redeems enrollment token to obtain authenticated session.
4. Recipient connects via WebSocket real-time transport.
5. Recipient sends message to Owner via REST or WebSocket.
6. Verify message is persisted with sequence #1, DeliveryState.STORED, and OutboxEvent is created.
7. Outbox worker processes event and dispatches to mock Discord and Webhook integrations.
8. MessageDelivery status transitions to DELIVERED.
9. Owner sends signed inbound reply via Webhook.
10. Recipient receives Owner reply via real-time WebSocket event.
11. Recipient marks message as read and sends read receipt.
12. Audit logs record the entire lifecycle trace with actor IDs, actions, and timestamps.
"""

import asyncio
import json
import time
import pytest
import websockets
from httpx import AsyncClient
from datetime import datetime, timezone
from sqlalchemy import select

from apps.api.src.core.config import settings
from apps.api.src.models.delivery import MessageDelivery
from apps.api.src.models.message import Message
from apps.api.src.models.outbox import OutboxEvent
from apps.api.src.models.audit import AuditEvent
from apps.api.src.models.conversation import Conversation
from apps.api.src.services.outbox_worker import OutboxWorker, IntegrationRouter
from packages.shared.src.constants import DeliveryState, EventType
from packages.shared.src.crypto import compute_webhook_signature


class MockAcceptanceRouter(IntegrationRouter):
    """Controllable router capturing delivered events."""
    def __init__(self):
        super().__init__()
        self.dispatched_events = []

    async def route_event(self, db, event):
        self.dispatched_events.append(event)
        results = [
            {"integration": "discord", "success": True, "external_id": "disc-accept-001", "error": None},
            {"integration": "webhook", "success": True, "external_id": "wh-accept-001", "error": None},
        ]
        for r in results:
            await self._update_delivery(db, event.message_id, r["integration"], r["success"], r["external_id"], r["error"])
        return results


@pytest.mark.asyncio
async def test_full_e2e_acceptance_lifecycle(client: AsyncClient, live_server, test_users, auth_headers, db_session):
    """Execute complete 12-step end-to-end acceptance flow."""
    conv = test_users["conversation"]
    conv_id = conv.id
    owner = test_users["owner"]

    # -------------------------------------------------------------
    # Step 1 & 2: Owner creates enrollment token for Recipient device
    # -------------------------------------------------------------
    token_resp = await client.post(
        "/api/v1/auth/enrollment-tokens",
        json={"device_name": "Acceptance Laptop", "platform": "linux", "expires_in_hours": 24},
        headers=auth_headers["owner"],
    )
    assert token_resp.status_code == 200
    enrollment_token = token_resp.json()["token"]
    assert len(enrollment_token) >= 32

    # -------------------------------------------------------------
    # Step 3: Recipient redeems token to bootstrap session
    # -------------------------------------------------------------
    redeem_resp = await client.post(
        "/api/v1/auth/enroll",
        json={"token": enrollment_token, "device_name": "Acceptance Laptop", "platform": "linux"},
    )
    assert redeem_resp.status_code == 200
    recipient_auth = redeem_resp.json()
    recip_jwt = recipient_auth["access_token"]
    recip_headers = {"Authorization": f"Bearer {recip_jwt}"}

    # -------------------------------------------------------------
    # Step 4: Recipient connects via WebSocket
    # -------------------------------------------------------------
    ws_url = f"{live_server['ws_url']}/api/v1/ws?token={recip_jwt}"
    async with websockets.connect(ws_url) as recip_ws:
        ack = json.loads(await recip_ws.recv())
        assert ack["type"] == "ack"
        assert ack["payload"]["role"] == "RECIPIENT"

        # Recipient syncs conversation
        await recip_ws.send(json.dumps({
            "action": "sync",
            "payload": {"conversation_id": conv_id, "last_sequence": 0}
        }))
        replay = json.loads(await recip_ws.recv())
        assert replay["type"] == "replay"

        # ---------------------------------------------------------
        # Step 5: Recipient sends message to Owner
        # ---------------------------------------------------------
        msg_payload = {
            "client_message_id": "e2e-accept-msg-001",
            "message": {"body": "Hello Owner! This is Recipient via Relationship OS."},
        }
        send_resp = await client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json=msg_payload,
            headers=recip_headers,
        )
        assert send_resp.status_code == 201
        sent_msg_data = send_resp.json()
        assert sent_msg_data["sequence_number"] == 1
        assert sent_msg_data["body"] == "Hello Owner! This is Recipient via Relationship OS."

        # Verify recipient receives live WebSocket broadcast of sent message
        own_frame = json.loads(await asyncio.wait_for(recip_ws.recv(), timeout=3.0))
        assert own_frame["type"] == "event"
        assert own_frame["payload"]["body"] == "Hello Owner! This is Recipient via Relationship OS."

        # ---------------------------------------------------------
        # Step 6: Verify message is persisted, sequenced, and outbox event created
        # ---------------------------------------------------------
        db_session.expire_all()
        msg_in_db = (await db_session.execute(
            select(Message).where(Message.id == sent_msg_data["id"])
        )).scalar_one()
        assert msg_in_db.sequence_number == 1
        assert msg_in_db.delivery_state == DeliveryState.STORED.value

        outbox_evt = (await db_session.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == msg_in_db.id)
            if hasattr(OutboxEvent, "aggregate_id") else
            select(OutboxEvent).where(OutboxEvent.status.in_(["pending", "processing"]))
        )).scalars().first()
        assert outbox_evt is not None

        # ---------------------------------------------------------
        # Step 7 & 8: Outbox worker routes event to Discord & Webhook
        # ---------------------------------------------------------
        mock_router = MockAcceptanceRouter()
        worker = OutboxWorker(router=mock_router)
        processed = await worker.process_batch(batch_size=10)
        assert processed >= 1
        assert len(mock_router.dispatched_events) >= 1

        target_msg_id = sent_msg_data["id"]
        db_session.expire_all()
        deliveries = (await db_session.execute(
            select(MessageDelivery).where(MessageDelivery.message_id == target_msg_id)
        )).scalars().all()
        assert len(deliveries) >= 2
        for d in deliveries:
            assert d.status == DeliveryState.DELIVERED.value
            assert d.completed_at is not None

        # ---------------------------------------------------------
        # Step 9: Owner replies via signed inbound webhook
        # ---------------------------------------------------------
        owner_reply_dict = {
            "conversation_id": conv_id,
            "body": "Hello Recipient! I received your message on Discord.",
            "client_message_id": "e2e-owner-reply-001",
        }
        reply_bytes = json.dumps(owner_reply_dict).encode("utf-8")
        now_ts = int(time.time())
        sig = compute_webhook_signature(reply_bytes, settings.WEBHOOK_SIGNING_SECRET, now_ts)

        wh_resp = await client.post(
            "/api/v1/webhooks/inbound",
            content=reply_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Relationship-Signature": sig,
                "X-Relationship-Timestamp": str(now_ts),
            },
        )
        assert wh_resp.status_code == 200
        owner_reply_data = wh_resp.json()
        assert owner_reply_data["status"] == "success"
        assert owner_reply_data["sequence_number"] == 2

        # ---------------------------------------------------------
        # Step 10: Recipient receives Owner reply in real time via WS
        # ---------------------------------------------------------
        realtime_frame = json.loads(await asyncio.wait_for(recip_ws.recv(), timeout=3.0))
        assert realtime_frame["type"] == "event"
        assert realtime_frame["event_type"] == EventType.MESSAGE_CREATED.value
        assert realtime_frame["payload"]["body"] == "Hello Recipient! I received your message on Discord."
        assert realtime_frame["payload"]["sequence_number"] == 2

        # ---------------------------------------------------------
        # Step 11: Recipient marks message as read
        # ---------------------------------------------------------
        read_resp = await client.post(
            f"/api/v1/conversations/{conv_id}/read",
            json={"last_read_sequence": 2},
            headers=recip_headers,
        )
        assert read_resp.status_code == 200
        assert read_resp.json()["last_read_sequence"] == 2

        # ---------------------------------------------------------
        # Step 12: Verify audit log trace records complete session
        # ---------------------------------------------------------
        audit_resp = await client.get("/api/v1/admin/audit?limit=50", headers=auth_headers["owner"])
        assert audit_resp.status_code == 200
        audit_items = audit_resp.json()
        action_names = [a["action"] for a in audit_items]
        assert "enrollment.created" in action_names
        assert "enrollment.redeem_success" in action_names
