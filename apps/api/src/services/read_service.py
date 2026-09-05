"""Read receipt and unread position service."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.models.participant import ConversationParticipant
from apps.api.src.models.message import Message


class ReadService:
    @staticmethod
    async def mark_read(
        db: AsyncSession,
        conversation_id: str,
        user_id: str,
        last_read_sequence: int,
    ) -> int:
        """Advance participant's last_read_sequence monotonically."""
        query = select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == user_id,
        )
        participant = (await db.execute(query)).scalar_one_or_none()
        if not participant:
            return 0

        # Monotonic update: only advance forward
        if last_read_sequence > participant.last_read_sequence:
            participant.last_read_sequence = last_read_sequence
            await db.flush()

        return participant.last_read_sequence

    @staticmethod
    async def get_unread_count(
        db: AsyncSession,
        conversation_id: str,
        user_id: str,
    ) -> int:
        """Calculate unread messages (newer than last_read_sequence and not sent by user)."""
        part_query = select(ConversationParticipant.last_read_sequence).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == user_id,
        )
        last_seq = (await db.execute(part_query)).scalar() or 0

        unread_query = select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id,
            Message.sequence_number > last_seq,
            Message.sender_id != user_id,
            Message.deleted_at.is_(None),
        )
        count = (await db.execute(unread_query)).scalar() or 0
        return count
