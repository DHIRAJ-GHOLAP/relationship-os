"""Integration tests for conversations, monotonic messaging, idempotency, pagination, and search."""

import uuid
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_conversations(client: AsyncClient, test_users, auth_headers):
    resp = await client.get("/api/v1/conversations", headers=auth_headers["recipient"])
    assert resp.status_code == 200
    convs = resp.json()
    assert len(convs) >= 1
    assert convs[0]["id"] == test_users["conversation"].id


@pytest.mark.asyncio
async def test_idempotent_message_send_and_monotonic_ordering(client: AsyncClient, test_users, auth_headers):
    conv_id = test_users["conversation"].id
    c_id_1 = str(uuid.uuid4())

    # Send 1st message
    resp1 = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"client_message_id": c_id_1, "message": {"type": "text", "body": "First message"}},
        headers=auth_headers["recipient"],
    )
    assert resp1.status_code == 201
    msg1 = resp1.json()
    assert msg1["sequence_number"] == 1
    assert msg1["body"] == "First message"

    # Send duplicate message with identical client_message_id -> must be idempotent!
    resp_dup = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"client_message_id": c_id_1, "message": {"type": "text", "body": "First message"}},
        headers=auth_headers["recipient"],
    )
    assert resp_dup.status_code == 201
    msg_dup = resp_dup.json()
    assert msg_dup["id"] == msg1["id"]
    assert msg_dup["sequence_number"] == 1

    # Send 2nd message -> sequence must be 2
    c_id_2 = str(uuid.uuid4())
    resp2 = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"client_message_id": c_id_2, "message": {"type": "text", "body": "Second message"}},
        headers=auth_headers["owner"],
    )
    assert resp2.status_code == 201
    msg2 = resp2.json()
    assert msg2["sequence_number"] == 2


@pytest.mark.asyncio
async def test_cursor_pagination(client: AsyncClient, test_users, auth_headers):
    conv_id = test_users["conversation"].id

    # Create 5 sequential messages
    for i in range(1, 6):
        await client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"client_message_id": f"msg_{i}", "message": {"type": "text", "body": f"Item {i}"}},
            headers=auth_headers["recipient"],
        )

    # 1. Page with limit=2
    res_limit = await client.get(
        f"/api/v1/conversations/{conv_id}/messages?limit=2",
        headers=auth_headers["recipient"],
    )
    assert res_limit.status_code == 200
    msgs = res_limit.json()
    assert len(msgs) == 2

    # 2. Before sequence 4 (should return messages 2 and 3 if limit=2)
    res_before = await client.get(
        f"/api/v1/conversations/{conv_id}/messages?before_seq=4&limit=2",
        headers=auth_headers["recipient"],
    )
    assert res_before.status_code == 200
    before_msgs = res_before.json()
    assert all(m["sequence_number"] < 4 for m in before_msgs)

    # 3. After sequence 2
    res_after = await client.get(
        f"/api/v1/conversations/{conv_id}/messages?after_seq=2",
        headers=auth_headers["recipient"],
    )
    assert res_after.status_code == 200
    after_msgs = res_after.json()
    assert all(m["sequence_number"] > 2 for m in after_msgs)


@pytest.mark.asyncio
async def test_read_receipts_and_unread_counts(client: AsyncClient, test_users, auth_headers):
    conv_id = test_users["conversation"].id

    # Recipient sends 2 messages
    await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"client_message_id": "unread_1", "message": {"type": "text", "body": "Hey"}},
        headers=auth_headers["recipient"],
    )
    await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"client_message_id": "unread_2", "message": {"type": "text", "body": "Are you there?"}},
        headers=auth_headers["recipient"],
    )

    # Owner checks unread count -> should be 2
    convs = (await client.get("/api/v1/conversations", headers=auth_headers["owner"])).json()
    target_conv = [c for c in convs if c["id"] == conv_id][0]
    assert target_conv["unread_count"] == 2

    # Owner marks read up to sequence 2
    read_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/read",
        json={"last_read_sequence": 2},
        headers=auth_headers["owner"],
    )
    assert read_resp.status_code == 200

    # Owner checks unread count again -> should be 0
    convs_after = (await client.get("/api/v1/conversations", headers=auth_headers["owner"])).json()
    assert [c for c in convs_after if c["id"] == conv_id][0]["unread_count"] == 0


@pytest.mark.asyncio
async def test_message_search(client: AsyncClient, test_users, auth_headers):
    conv_id = test_users["conversation"].id
    await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"client_message_id": "search_1", "message": {"type": "text", "body": "Remember our trip to Paris?"}},
        headers=auth_headers["recipient"],
    )

    # Search for "paris"
    resp = await client.get(
        f"/api/v1/conversations/{conv_id}/search?q=Paris",
        headers=auth_headers["owner"],
    )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert "Paris" in results[0]["body"]


@pytest.mark.asyncio
async def test_message_too_large_rejected(client: AsyncClient, test_users, auth_headers):
    conv_id = test_users["conversation"].id
    oversized_body = "x" * 5000

    resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"client_message_id": "huge_msg", "message": {"type": "text", "body": oversized_body}},
        headers=auth_headers["recipient"],
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "MESSAGE_TOO_LARGE"
