import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.src.core.config import settings
from apps.api.src.core.exceptions import (
    ForbiddenException,
    MessageTooLargeException,
    NotFoundException,
)
from apps.api.src.models.conversation import Conversation
from apps.api.src.models.participant import ConversationParticipant
from apps.api.src.models.message import Message
from apps.api.src.models.outbox import OutboxEvent
from apps.api.src.models.delivery import MessageDelivery
from packages.shared.src.constants import DeliveryState, EventType, MessageType, UserRole
from packages.shared.src.models import CanonicalMessageEvent, MessagePayload

_conversation_locks: Dict[str, asyncio.Lock] = {}


def _get_conv_lock(conversation_id: str) -> asyncio.Lock:
    if conversation_id not in _conversation_locks:
        _conversation_locks[conversation_id] = asyncio.Lock()
    return _conversation_locks[conversation_id]


class MessageService:
    @staticmethod
    async def get_or_create_private_conversation(
        db: AsyncSession,
        owner_id: str,
        recipient_id: str,
        title: Optional[str] = None,
    ) -> Conversation:
        """Fetch existing canonical private room or initialize it with both participants."""
        # Find direct conversation where both are participants
        query = (
            select(Conversation)
            .join(ConversationParticipant, Conversation.id == ConversationParticipant.conversation_id)
            .where(ConversationParticipant.user_id.in_([owner_id, recipient_id]))
            .group_by(Conversation.id)
            .having(func.count(ConversationParticipant.id) >= 2)
        )
        conv = (await db.execute(query)).scalars().first()
        if conv:
            return conv

        # Create new canonical conversation
        conv = Conversation(
            title=title or settings.ROOM_NAME,
            type="direct",
            status="active",
            metadata_json=json.dumps({"description": "Primary private room"}),
            created_at=datetime.now(timezone.utc),
        )
        db.add(conv)
        await db.flush()

        # Add participants
        p1 = ConversationParticipant(conversation_id=conv.id, user_id=owner_id, last_read_sequence=0)
        p2 = ConversationParticipant(conversation_id=conv.id, user_id=recipient_id, last_read_sequence=0)
        db.add_all([p1, p2])
        await db.flush()
        return conv

    @staticmethod
    async def verify_conversation_access(
        db: AsyncSession,
        conversation_id: str,
        user_id: str,
        user_role: UserRole,
    ) -> Conversation:
        """Verify that user has permission to read or write in conversation."""
        conv_query = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
        conv = conv_query.scalar_one_or_none()
        if not conv:
            raise NotFoundException("Conversation not found")

        # Admin has oversight access
        if user_role == UserRole.ADMIN:
            return conv

        part_query = await db.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == user_id,
            )
        )
        participant = part_query.scalar_one_or_none()
        if not participant:
            raise ForbiddenException("User is not an authorized participant in this conversation")

        if conv.status == "locked" and user_role == UserRole.RECIPIENT:
            raise ForbiddenException("This conversation is currently locked by administrator")

        return conv

    @staticmethod
    async def send_message(
        db: AsyncSession,
        conversation_id: str,
        sender_id: str,
        sender_name: str,
        sender_role: UserRole,
        client_message_id: str,
        payload: MessagePayload,
        origin: str = "chat",
    ) -> Tuple[Message, bool]:
        """
        Idempotently create and persist a canonical message with atomic sequence allocation
        and durable outbox event emission.
        Returns (message, is_new: bool).
        """
        # Validate message length
        if len(payload.body) > settings.MAX_MESSAGE_LENGTH:
            raise MessageTooLargeException(
                f"Message length ({len(payload.body)}) exceeds maximum of {settings.MAX_MESSAGE_LENGTH} characters"
            )

        async with _get_conv_lock(conversation_id):
            # Idempotency check: if message with this client_message_id exists, return it
            existing_query = await db.execute(
                select(Message).where(
                    Message.conversation_id == conversation_id,
                    Message.client_message_id == client_message_id,
                )
            )
            existing = existing_query.scalar_one_or_none()
            if existing:
                return existing, False

            # Monotonic sequence allocation per conversation
            seq_query = await db.execute(
                select(func.coalesce(func.max(Message.sequence_number), 0)).where(
                    Message.conversation_id == conversation_id
                )
            )
            current_max_seq = seq_query.scalar() or 0
            next_seq = current_max_seq + 1

            # Determine initial delivery state
            initial_state = DeliveryState.DELIVERED if sender_role == UserRole.OWNER else DeliveryState.STORED

            msg_id = str(uuid.uuid4())
            msg = Message(
                id=msg_id,
                conversation_id=conversation_id,
                sender_id=sender_id,
                message_type=payload.type.value if hasattr(payload.type, "value") else str(payload.type),
                body=payload.body,
                client_message_id=client_message_id,
                sequence_number=next_seq,
                delivery_state=initial_state.value,
                metadata_json=json.dumps({"origin": origin, "attachments": payload.attachments or []}),
                created_at=datetime.now(timezone.utc),
            )

            delivery_recs = [
                MessageDelivery(
                    message_id=msg_id,
                    integration_type=integration,
                    status=DeliveryState.QUEUED.value,
                    attempt_count=0,
                    first_attempted_at=None,
                )
                for integration in ["discord", "webhook"]
            ]

            # Canonical Event Creation for durable outbox
            canonical_event = CanonicalMessageEvent(
                event_type=EventType.MESSAGE_CREATED,
                conversation_id=conversation_id,
                message_id=msg_id,
                sender_id=sender_id,
                sender_role=sender_role,
                sender_name=sender_name,
                sequence=next_seq,
                timestamp=msg.created_at,
                origin=origin,
                message=payload,
                metadata={"client_message_id": client_message_id},
            )

            outbox = OutboxEvent(
                event_type=EventType.MESSAGE_CREATED.value,
                payload_json=canonical_event.model_dump_json(),
                status="pending",
                retry_count=0,
                max_retries=settings.WEBHOOK_MAX_RETRIES,
                next_attempt_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )

            try:
                db.add(msg)
                db.add_all(delivery_recs)
                db.add(outbox)
                await db.flush()
                return msg, True
            except IntegrityError:
                await db.rollback()
                # Check if it was an idempotency conflict
                retry_exist = await db.execute(
                    select(Message).where(
                        Message.conversation_id == conversation_id,
                        Message.client_message_id == client_message_id,
                    )
                )
                existing = retry_exist.scalar_one_or_none()
                if existing:
                    return existing, False
                raise

    @staticmethod
    async def get_history(
        db: AsyncSession,
        conversation_id: str,
        before_seq: Optional[int] = None,
        after_seq: Optional[int] = None,
        limit: int = 50,
    ) -> List[Message]:
        """Cursor-paginated message history using monotonic sequence numbers."""
        clamped_limit = max(1, min(limit, 100))
        query = select(Message).options(selectinload(Message.sender)).where(Message.conversation_id == conversation_id)

        if before_seq is not None:
            query = query.where(Message.sequence_number < before_seq).order_by(Message.sequence_number.desc())
        elif after_seq is not None:
            query = query.where(Message.sequence_number > after_seq).order_by(Message.sequence_number.asc())
        else:
            query = query.order_by(Message.sequence_number.desc())

        query = query.limit(clamped_limit)
        results = (await db.execute(query)).scalars().all()
        # Always return sorted chronologically by sequence asc for UI rendering
        sorted_results = sorted(results, key=lambda m: m.sequence_number)
        return sorted_results

    @staticmethod
    async def search_messages(
        db: AsyncSession,
        conversation_id: str,
        query_text: str,
        limit: int = 50,
    ) -> List[Message]:
        """Search message bodies within a conversation."""
        clamped_limit = max(1, min(limit, 100))
        search_pattern = f"%{query_text.strip()}%"
        stmt = (
            select(Message)
            .options(selectinload(Message.sender))
            .where(
                Message.conversation_id == conversation_id,
                Message.body.ilike(search_pattern),
                Message.deleted_at.is_(None),
            )
            .order_by(Message.sequence_number.desc())
            .limit(clamped_limit)
        )
        results = (await db.execute(stmt)).scalars().all()
        return list(results)
