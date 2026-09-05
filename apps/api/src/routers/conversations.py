"""Conversation and Messaging REST API Router."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.core.database import get_db
from apps.api.src.core.security import get_current_user_and_session
from apps.api.src.models.conversation import Conversation
from apps.api.src.models.participant import ConversationParticipant
from apps.api.src.models.message import Message
from apps.api.src.services.message_service import MessageService
from apps.api.src.services.read_service import ReadService
from apps.api.src.routers.websocket import ws_manager
from packages.shared.src.constants import DeliveryState, EventType, MessageType, UserRole
from packages.shared.src.models import (
    MessagePayload,
    MessageResponse,
    MessageSendRequest,
    ReadReceiptRequest,
)

router = APIRouter(prefix="/api/v1/conversations", tags=["Conversations"])


class ConversationResponse(BaseModel):
    id: str
    title: str
    type: str
    status: str
    created_at: str
    unread_count: int = 0


@router.get("", response_model=List[ConversationResponse])
async def list_conversations(
    auth=Depends(get_current_user_and_session),
    db: AsyncSession = Depends(get_db),
):
    """List conversations accessible to the current authenticated user."""
    user = auth["user"]
    if user.role == UserRole.ADMIN:
        query = select(Conversation).order_by(Conversation.updated_at.desc())
        convs = (await db.execute(query)).scalars().all()
    else:
        query = (
            select(Conversation)
            .join(ConversationParticipant, Conversation.id == ConversationParticipant.conversation_id)
            .where(ConversationParticipant.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
        )
        convs = (await db.execute(query)).scalars().all()

    results = []
    for c in convs:
        unread = await ReadService.get_unread_count(db, conversation_id=c.id, user_id=user.id)
        results.append(
            ConversationResponse(
                id=c.id,
                title=c.title,
                type=c.type,
                status=c.status,
                created_at=c.created_at.isoformat(),
                unread_count=unread,
            )
        )
    return results


@router.get("/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_message_history(
    conversation_id: str,
    before_seq: Optional[int] = Query(None, description="Cursor for messages before this sequence number"),
    after_seq: Optional[int] = Query(None, description="Cursor for messages after this sequence number"),
    limit: int = Query(50, ge=1, le=100),
    auth=Depends(get_current_user_and_session),
    db: AsyncSession = Depends(get_db),
):
    """Cursor-paginated message history for a conversation."""
    user = auth["user"]
    await MessageService.verify_conversation_access(db, conversation_id, user.id, user.role)

    messages = await MessageService.get_history(
        db, conversation_id=conversation_id, before_seq=before_seq, after_seq=after_seq, limit=limit
    )

    return [
        MessageResponse(
            id=m.id,
            conversation_id=m.conversation_id,
            sender_id=m.sender_id,
            sender_name=m.sender.display_name if m.sender else None,
            message_type=MessageType(m.message_type) if m.message_type in [e.value for e in MessageType] else MessageType.TEXT,
            body=m.body,
            created_at=m.created_at,
            edited_at=m.edited_at,
            deleted_at=m.deleted_at,
            client_message_id=m.client_message_id,
            sequence_number=m.sequence_number,
            delivery_state=DeliveryState(m.delivery_state) if m.delivery_state in [e.value for e in DeliveryState] else DeliveryState.DELIVERED,
        )
        for m in messages
    ]


@router.post("/{conversation_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    conversation_id: str,
    body: MessageSendRequest,
    auth=Depends(get_current_user_and_session),
    db: AsyncSession = Depends(get_db),
):
    """Send a message idempotently with server sequence allocation and live broadcast."""
    user = auth["user"]
    await MessageService.verify_conversation_access(db, conversation_id, user.id, user.role)

    msg, is_new = await MessageService.send_message(
        db=db,
        conversation_id=conversation_id,
        sender_id=user.id,
        sender_name=user.display_name,
        sender_role=user.role,
        client_message_id=body.client_message_id,
        payload=body.message,
        origin="rest",
    )

    # Broadcast to real-time subscribers if it is newly created
    if is_new:
        from datetime import datetime, timezone
        await ws_manager.broadcast_to_room(conversation_id, {
            "type": "event",
            "event_id": msg.id,
            "event_type": EventType.MESSAGE_CREATED.value,
            "payload": {
                "id": msg.id,
                "conversation_id": msg.conversation_id,
                "sender_id": msg.sender_id,
                "sender_name": user.display_name,
                "message_type": msg.message_type,
                "body": msg.body,
                "sequence_number": msg.sequence_number,
                "delivery_state": msg.delivery_state,
                "created_at": msg.created_at.isoformat(),
                "client_message_id": msg.client_message_id,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return MessageResponse(
        id=msg.id,
        conversation_id=msg.conversation_id,
        sender_id=msg.sender_id,
        sender_name=user.display_name,
        message_type=MessageType(msg.message_type) if msg.message_type in [e.value for e in MessageType] else MessageType.TEXT,
        body=msg.body,
        created_at=msg.created_at,
        edited_at=msg.edited_at,
        deleted_at=msg.deleted_at,
        client_message_id=msg.client_message_id,
        sequence_number=msg.sequence_number,
        delivery_state=DeliveryState(msg.delivery_state) if msg.delivery_state in [e.value for e in DeliveryState] else DeliveryState.DELIVERED,
    )


@router.post("/{conversation_id}/read")
async def mark_conversation_read(
    conversation_id: str,
    body: ReadReceiptRequest,
    auth=Depends(get_current_user_and_session),
    db: AsyncSession = Depends(get_db),
):
    """Monotonically advance the user's read position in the conversation."""
    user = auth["user"]
    await MessageService.verify_conversation_access(db, conversation_id, user.id, user.role)

    last_seq = await ReadService.mark_read(
        db, conversation_id=conversation_id, user_id=user.id, last_read_sequence=body.last_read_sequence
    )

    # Broadcast read receipt
    await ws_manager.broadcast_to_room(conversation_id, {
        "type": "read",
        "payload": {
            "conversation_id": conversation_id,
            "user_id": user.id,
            "last_read_sequence": last_seq,
        }
    })

    return {"conversation_id": conversation_id, "last_read_sequence": last_seq}


@router.get("/{conversation_id}/search", response_model=List[MessageResponse])
async def search_messages(
    conversation_id: str,
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(20, ge=1, le=50),
    auth=Depends(get_current_user_and_session),
    db: AsyncSession = Depends(get_db),
):
    """Search message bodies within an authorized conversation."""
    user = auth["user"]
    await MessageService.verify_conversation_access(db, conversation_id, user.id, user.role)

    messages = await MessageService.search_messages(
        db, conversation_id=conversation_id, query_text=q, limit=limit
    )

    return [
        MessageResponse(
            id=m.id,
            conversation_id=m.conversation_id,
            sender_id=m.sender_id,
            sender_name=m.sender.display_name if m.sender else None,
            message_type=MessageType(m.message_type) if m.message_type in [e.value for e in MessageType] else MessageType.TEXT,
            body=m.body,
            created_at=m.created_at,
            edited_at=m.edited_at,
            deleted_at=m.deleted_at,
            client_message_id=m.client_message_id,
            sequence_number=m.sequence_number,
            delivery_state=DeliveryState(m.delivery_state) if m.delivery_state in [e.value for e in DeliveryState] else DeliveryState.DELIVERED,
        )
        for m in messages
    ]
