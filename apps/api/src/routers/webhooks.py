"""Inbound Webhook receiver for verified owner responses."""

import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.core.config import settings
from apps.api.src.core.database import get_db
from apps.api.src.core.exceptions import AppException, AuthInvalidException
from apps.api.src.models.user import User
from apps.api.src.models.conversation import Conversation
from apps.api.src.services.message_service import MessageService
from apps.api.src.routers.websocket import ws_manager
from packages.shared.src.constants import ErrorCode, EventType, UserRole
from packages.shared.src.crypto import verify_webhook_signature
from packages.shared.src.models import MessagePayload

router = APIRouter(prefix="/api/v1/webhooks", tags=["Inbound Webhooks"])


@router.post("/inbound")
async def receive_inbound_webhook(
    request: Request,
    x_relationship_signature: str = Header(..., alias="X-Relationship-Signature"),
    x_relationship_timestamp: int = Header(..., alias="X-Relationship-Timestamp"),
    db: AsyncSession = Depends(get_db),
):
    """
    Process signed inbound owner reply from an external webhook.
    Requires valid HMAC-SHA256 signature and fresh timestamp window.
    """
    raw_body = await request.body()

    # 1. Verify HMAC Signature and Anti-Replay Timestamp
    is_valid, reason = verify_webhook_signature(
        payload_bytes=raw_body,
        secret=settings.WEBHOOK_SIGNING_SECRET,
        signature_header=x_relationship_signature,
        timestamp=x_relationship_timestamp,
        tolerance_seconds=300,
    )
    if not is_valid:
        raise AuthInvalidException(f"Invalid webhook signature: {reason}")

    # 2. Parse payload
    try:
        data = json.loads(raw_body)
    except Exception:
        raise AppException(ErrorCode.INVALID_REQUEST, "Malformed JSON payload in webhook")

    conversation_id = data.get("conversation_id")
    body_text = data.get("body")
    client_msg_id = data.get("client_message_id") or f"wh_in_{datetime.now(timezone.utc).timestamp()}"

    if not conversation_id or not body_text:
        raise AppException(ErrorCode.INVALID_REQUEST, "Missing conversation_id or body in webhook payload")

    # 3. Verify owner account exists
    owner_query = await db.execute(select(User).where(User.role.in_([UserRole.OWNER, UserRole.ADMIN])))
    owner = owner_query.scalars().first()
    if not owner:
        raise AppException(ErrorCode.INTERNAL_ERROR, "No owner account configured to attribute webhook reply")

    # 4. Idempotently persist canonical message
    msg, is_new = await MessageService.send_message(
        db=db,
        conversation_id=conversation_id,
        sender_id=owner.id,
        sender_name=owner.display_name,
        sender_role=owner.role,
        client_message_id=client_msg_id,
        payload=MessagePayload(body=body_text),
        origin="webhook",
    )
    await db.commit()

    # 5. Broadcast in real time to recipient
    if is_new:
        await ws_manager.broadcast_to_room(conversation_id, {
            "type": "event",
            "event_id": msg.id,
            "event_type": EventType.MESSAGE_CREATED.value,
            "payload": {
                "id": msg.id,
                "conversation_id": msg.conversation_id,
                "sender_id": msg.sender_id,
                "sender_name": owner.display_name,
                "message_type": msg.message_type,
                "body": msg.body,
                "sequence_number": msg.sequence_number,
                "delivery_state": msg.delivery_state,
                "created_at": msg.created_at.isoformat(),
                "client_message_id": msg.client_message_id,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return {
        "status": "success",
        "message_id": msg.id,
        "sequence_number": msg.sequence_number,
    }
