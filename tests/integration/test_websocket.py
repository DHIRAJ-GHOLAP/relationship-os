"""Integration tests for WebSocket real-time transport with live async client."""

import asyncio
import json
import pytest
import websockets


@pytest.mark.asyncio
async def test_ws_unauthenticated_connection_rejected(live_server):
    """Unauthenticated connection with invalid token frame is rejected."""
    ws_url = f"{live_server['ws_url']}/api/v1/ws"
    async with websockets.connect(ws_url) as ws:
        # Send bad auth frame
        await ws.send(json.dumps({"action": "auth", "payload": {"token": "invalid_token_jwt"}}))
        msg = await ws.recv()
        data = json.loads(msg)
        assert data["type"] == "error"
        assert data["payload"]["code"] == "AUTH_INVALID"


@pytest.mark.asyncio
async def test_ws_query_param_auth_and_ping_pong(live_server, test_users, auth_headers):
    """Connecting with query param token establishes session and supports ping/pong."""
    token = auth_headers["recipient"]["Authorization"].split(" ")[1]
    ws_url = f"{live_server['ws_url']}/api/v1/ws?token={token}"

    async with websockets.connect(ws_url) as ws:
        ack_raw = await ws.recv()
        ack = json.loads(ack_raw)
        assert ack["type"] == "ack"
        assert ack["payload"]["role"] == "RECIPIENT"

        # Send heartbeat ping
        await ws.send(json.dumps({"action": "ping"}))
        pong_raw = await ws.recv()
        pong = json.loads(pong_raw)
        assert pong["type"] == "pong"
        assert "timestamp" in pong


@pytest.mark.asyncio
async def test_ws_sync_sequence_replay(live_server, test_users, auth_headers):
    """Test joining conversation and receiving monotonic sequence replay."""
    token = auth_headers["owner"]["Authorization"].split(" ")[1]
    conv = test_users["conversation"]
    ws_url = f"{live_server['ws_url']}/api/v1/ws?token={token}"

    async with websockets.connect(ws_url) as ws:
        ack = json.loads(await ws.recv())
        assert ack["type"] == "ack"

        # Sync conversation
        await ws.send(json.dumps({
            "action": "sync",
            "payload": {
                "conversation_id": conv.id,
                "last_sequence": 0,
            }
        }))
        replay = json.loads(await ws.recv())
        assert replay["type"] == "replay"
        assert replay["payload"]["conversation_id"] == conv.id
        assert isinstance(replay["payload"]["messages"], list)


@pytest.mark.asyncio
async def test_ws_live_chat_and_typing_between_parties(live_server, test_users, auth_headers):
    """Test live broadcast of messages, typing indicators, and read receipts between two clients."""
    owner_token = auth_headers["owner"]["Authorization"].split(" ")[1]
    recip_token = auth_headers["recipient"]["Authorization"].split(" ")[1]
    conv = test_users["conversation"]

    owner_ws_url = f"{live_server['ws_url']}/api/v1/ws?token={owner_token}"
    recip_ws_url = f"{live_server['ws_url']}/api/v1/ws?token={recip_token}"

    async with websockets.connect(owner_ws_url) as owner_ws:
        owner_ack = json.loads(await owner_ws.recv())
        assert owner_ack["type"] == "ack"

        # Owner joins room
        await owner_ws.send(json.dumps({
            "action": "sync",
            "payload": {"conversation_id": conv.id, "last_sequence": 0}
        }))
        await owner_ws.recv()  # Consume replay

        async with websockets.connect(recip_ws_url) as recip_ws:
            recip_ack = json.loads(await recip_ws.recv())
            assert recip_ack["type"] == "ack"

            # Recipient joins room
            await recip_ws.send(json.dumps({
                "action": "sync",
                "payload": {"conversation_id": conv.id, "last_sequence": 0}
            }))
            await recip_ws.recv()  # Consume replay

            # Owner should receive recipient's presence broadcast
            presence_frame = json.loads(await asyncio.wait_for(owner_ws.recv(), timeout=2.0))
            assert presence_frame["type"] == "presence"
            assert presence_frame["payload"]["status"] == "online"

            # Recipient sends typing indicator
            await recip_ws.send(json.dumps({
                "action": "typing",
                "payload": {"conversation_id": conv.id, "typing": True}
            }))
            typing_frame = json.loads(await asyncio.wait_for(owner_ws.recv(), timeout=2.0))
            assert typing_frame["type"] == "typing"
            assert typing_frame["payload"]["is_typing"] is True

            # Recipient sends real-time message
            await recip_ws.send(json.dumps({
                "action": "send",
                "payload": {
                    "conversation_id": conv.id,
                    "client_message_id": "ws-realtime-msg-999",
                    "body": "Hello over WebSocket!",
                }
            }))

            # Both recipient and owner receive broadcast event
            recip_event = json.loads(await asyncio.wait_for(recip_ws.recv(), timeout=2.0))
            assert recip_event["type"] == "event"
            assert recip_event["payload"]["body"] == "Hello over WebSocket!"
            seq = recip_event["payload"]["sequence_number"]
            assert seq > 0

            owner_event = json.loads(await asyncio.wait_for(owner_ws.recv(), timeout=2.0))
            assert owner_event["type"] == "event"
            assert owner_event["payload"]["body"] == "Hello over WebSocket!"

            # Owner sends read receipt
            await owner_ws.send(json.dumps({
                "action": "read",
                "payload": {
                    "conversation_id": conv.id,
                    "last_read_sequence": seq,
                }
            }))

            # Recipient receives read receipt broadcast
            read_receipt = json.loads(await asyncio.wait_for(recip_ws.recv(), timeout=2.0))
            assert read_receipt["type"] == "read"
            assert read_receipt["payload"]["last_read_sequence"] == seq
