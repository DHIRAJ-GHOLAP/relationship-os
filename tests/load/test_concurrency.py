"""Load and concurrency tests for monotonic sequence numbering and idempotent race handling."""

import asyncio
import pytest
from httpx import AsyncClient

from apps.api.src.models.message import Message
from sqlalchemy import select, func


@pytest.mark.asyncio
async def test_concurrent_message_monotonic_sequence_allocation(client: AsyncClient, auth_headers, test_users, db_session):
    """Multiple concurrent sends must result in strictly monotonic, gapless sequence numbers."""
    conv = test_users["conversation"]
    num_messages = 20

    async def send_msg(i: int):
        resp = await client.post(
            f"/api/v1/conversations/{conv.id}/messages",
            json={
                "client_message_id": f"concurrent-seq-{i}",
                "message": {"body": f"Concurrent message #{i}"},
            },
            headers=auth_headers["recipient"],
        )
        assert resp.status_code == 201
        return resp.json()["sequence_number"]

    # Launch all 20 sends concurrently
    sequences = await asyncio.gather(*(send_msg(i) for i in range(num_messages)))

    # Verify all sequence numbers are unique
    assert len(sequences) == num_messages
    assert len(set(sequences)) == num_messages

    # Verify they form a contiguous sorted set starting from 1
    sorted_seqs = sorted(sequences)
    expected_seqs = list(range(1, num_messages + 1))
    assert sorted_seqs == expected_seqs


@pytest.mark.asyncio
async def test_concurrent_idempotent_deduplication_race(client: AsyncClient, auth_headers, test_users, db_session):
    """Concurrent identical client_message_id sends must deduplicate cleanly with no duplicates."""
    conv = test_users["conversation"]
    race_client_id = "race-client-dedup-999"
    concurrency_count = 10

    async def send_duplicate():
        return await client.post(
            f"/api/v1/conversations/{conv.id}/messages",
            json={
                "client_message_id": race_client_id,
                "message": {"body": "Identical content in race condition"},
            },
            headers=auth_headers["recipient"],
        )

    responses = await asyncio.gather(*(send_duplicate() for _ in range(concurrency_count)))

    # All responses must succeed (201 Created or 200 OK)
    for r in responses:
        assert r.status_code in (200, 201)

    # All responses must reference the exact same message ID and sequence number
    message_ids = {r.json()["id"] for r in responses}
    sequences = {r.json()["sequence_number"] for r in responses}

    assert len(message_ids) == 1
    assert len(sequences) == 1

    # Verify database has exactly 1 record for this client_message_id
    db_session.expire_all()
    count = (await db_session.execute(
        select(func.count(Message.id)).where(Message.client_message_id == race_client_id)
    )).scalar()
    assert count == 1
