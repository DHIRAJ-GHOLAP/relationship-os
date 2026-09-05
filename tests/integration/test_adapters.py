"""Integration tests for Discord and Webhook adapters and Inbound Webhook API."""

import json
import time
from datetime import datetime, timezone
import httpx
import pytest
from httpx import AsyncClient

from apps.api.src.core.config import settings
from integrations.discord.src.adapter import DiscordAdapter, sanitize_discord_content
from integrations.webhook.src.adapter import WebhookAdapter
from packages.shared.src.crypto import compute_webhook_signature
from packages.shared.src.models import CanonicalMessageEvent, MessagePayload
from packages.shared.src.constants import EventType, UserRole


# ==========================================
# 1. Discord Adapter Tests
# ==========================================

def test_discord_mention_sanitization():
    """Ensure dangerous mentions are neutralized."""
    raw = "Hey @everyone check out <@123456789> and @here for updates!"
    clean = sanitize_discord_content(raw)

    assert "@everyone" not in clean
    assert "@here" not in clean
    assert "<@123456789>" not in clean
    assert "[mention redacted]" in clean
    assert "@\u200beveryone" in clean
    assert "@\u200bhere" in clean


@pytest.mark.asyncio
async def test_discord_loop_prevention():
    """Messages originating from Discord must NOT be echoed back to Discord."""
    adapter = DiscordAdapter()
    event = CanonicalMessageEvent(
        event_id="evt-disc-loop",
        event_type=EventType.MESSAGE_CREATED,
        conversation_id="c1",
        message_id="m1",
        sender_id="u1",
        sequence=1,
        origin="discord",  # Origin is Discord!
        message=MessagePayload(body="Echo check"),
    )

    success, ext_id, err = await adapter.send(event)
    assert success is True
    assert ext_id == "skipped_loop_prevention"
    assert err is None


@pytest.mark.asyncio
async def test_discord_send_via_mock_transport():
    """Verify Discord payload formatting and transmission."""
    called_requests = []

    def mock_handler(request: httpx.Request):
        called_requests.append(request)
        return httpx.Response(200, json={"id": "discord-msg-999"})

    transport = httpx.MockTransport(mock_handler)
    mock_client = httpx.AsyncClient(transport=transport)

    original_enabled = settings.DISCORD_ENABLED
    original_webhook = settings.DISCORD_WEBHOOK_URL
    settings.DISCORD_ENABLED = True
    settings.DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/123/fake_token"

    try:
        adapter = DiscordAdapter(client=mock_client)
        event = CanonicalMessageEvent(
            event_id="evt-disc-send",
            event_type=EventType.MESSAGE_CREATED,
            conversation_id="c1",
            message_id="m1",
            sender_id="u1",
            sender_name="Recipient Bob",
            sequence=42,
            origin="chat",
            message=MessagePayload(body="Hello Discord!"),
        )
        success, ext_id, err = await adapter.send(event)
        assert success is True
        assert ext_id == "discord-msg-999"
        assert len(called_requests) == 1

        sent_body = json.loads(called_requests[0].content)
        assert "Hello Discord!" in sent_body["content"]
        assert sent_body["allowed_mentions"] == {"parse": []}
    finally:
        settings.DISCORD_ENABLED = original_enabled
        settings.DISCORD_WEBHOOK_URL = original_webhook


@pytest.mark.asyncio
async def test_discord_multi_bot_failover():
    """Verify that when the primary bot token fails, the adapter automatically fails over to backup bot."""
    original_enabled = settings.DISCORD_ENABLED
    original_webhook = settings.DISCORD_WEBHOOK_URL
    original_token = settings.DISCORD_BOT_TOKEN
    original_backups = settings.DISCORD_BACKUP_TOKENS
    original_channel = settings.DISCORD_CHANNEL_ID

    called_auth_headers = []

    def handle_bot_request(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        called_auth_headers.append(auth)
        if "primary_token" in auth:
            # Simulate rate limit on primary bot
            return httpx.Response(429, json={"message": "You are being rate limited."})
        elif "backup_token_alice" in auth:
            # Backup bot succeeds
            return httpx.Response(200, json={"id": "discord-msg-alice-777"})
        return httpx.Response(500, json={"error": "Unknown bot"})

    transport = httpx.MockTransport(handle_bot_request)
    mock_client = httpx.AsyncClient(transport=transport)

    settings.DISCORD_ENABLED = True
    settings.DISCORD_WEBHOOK_URL = None
    settings.DISCORD_BOT_TOKEN = "primary_token"
    settings.DISCORD_BACKUP_TOKENS = "backup_token_alice,backup_token_john"
    settings.DISCORD_CHANNEL_ID = "123456789"

    try:
        adapter = DiscordAdapter(client=mock_client)
        event = CanonicalMessageEvent(
            event_id="evt-disc-failover",
            event_type=EventType.MESSAGE_CREATED,
            conversation_id="c1",
            message_id="m1",
            sender_id="u1",
            sender_name="Alice",
            sequence=10,
            origin="chat",
            message=MessagePayload(body="Testing failover"),
        )
        success, ext_id, err = await adapter.send(event)
        assert success is True
        assert ext_id == "discord-msg-alice-777"
        assert len(called_auth_headers) == 2
        assert "primary_token" in called_auth_headers[0]
        assert "backup_token_alice" in called_auth_headers[1]
    finally:
        settings.DISCORD_ENABLED = original_enabled
        settings.DISCORD_WEBHOOK_URL = original_webhook
        settings.DISCORD_BOT_TOKEN = original_token
        settings.DISCORD_BACKUP_TOKENS = original_backups
        settings.DISCORD_CHANNEL_ID = original_channel


# ==========================================
# 2. Webhook Adapter Tests (SSRF & HMAC)
# ==========================================

@pytest.mark.asyncio
async def test_webhook_adapter_ssrf_blocking():
    """Webhook adapter must reject private IP addresses and metadata endpoints."""
    adapter = WebhookAdapter()
    event = CanonicalMessageEvent(
        event_id="evt-wh-ssrf",
        event_type=EventType.MESSAGE_CREATED,
        conversation_id="c1",
        message_id="m1",
        sender_id="u1",
        sequence=1,
        message=MessagePayload(body="SSRF Test"),
    )

    # 1. Localhost
    success, _, err = await adapter.send_to_endpoint(
        url="http://127.0.0.1:9000/webhook",
        secret="test_secret",
        event=event,
        allow_localhost=False,
    )
    assert success is False
    assert "SSRF Blocked" in err

    # 2. AWS metadata
    success, _, err = await adapter.send_to_endpoint(
        url="http://169.254.169.254/latest/meta-data/",
        secret="test_secret",
        event=event,
        allow_localhost=False,
    )
    assert success is False
    assert "SSRF Blocked" in err


@pytest.mark.asyncio
async def test_webhook_adapter_hmac_signing_transmission():
    """Webhook adapter correctly signs payload with HMAC-SHA256 and transmits headers."""
    called_requests = []

    def mock_handler(request: httpx.Request):
        called_requests.append(request)
        return httpx.Response(200, json={"received": True})

    transport = httpx.MockTransport(mock_handler)
    mock_client = httpx.AsyncClient(transport=transport)

    adapter = WebhookAdapter(client=mock_client)
    event = CanonicalMessageEvent(
        event_id="evt-wh-sign",
        event_type=EventType.MESSAGE_CREATED,
        conversation_id="c1",
        message_id="m1",
        sender_id="u1",
        sequence=5,
        message=MessagePayload(body="Signed Payload"),
    )

    secret = "SuperSecretSigningKey123!"
    success, ext_id, err = await adapter.send_to_endpoint(
        url="http://127.0.0.1:8080/wh",
        secret=secret,
        event=event,
        allow_localhost=True,
    )

    assert success is True
    assert len(called_requests) == 1

    req = called_requests[0]
    sig_header = req.headers.get("X-Relationship-Signature")
    ts_header = req.headers.get("X-Relationship-Timestamp")
    assert sig_header is not None
    assert sig_header.startswith("v1=")
    assert ts_header is not None


# ==========================================
# 3. Inbound Webhook Endpoint Tests
# ==========================================

@pytest.mark.asyncio
async def test_inbound_webhook_signature_verification(client: AsyncClient, test_users):
    """Inbound webhook verifies HMAC signature, timestamp window, and creates owner message."""
    conv = test_users["conversation"]
    secret = settings.WEBHOOK_SIGNING_SECRET

    payload_dict = {
        "conversation_id": conv.id,
        "body": "Owner replied via webhook!",
        "client_message_id": "wh-reply-001",
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    now_ts = int(time.time())
    valid_sig = compute_webhook_signature(payload_bytes, secret, now_ts)

    # 1. Invalid signature is rejected with 401
    bad_resp = await client.post(
        "/api/v1/webhooks/inbound",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Relationship-Signature": "sha256=invalid_hash_signature",
            "X-Relationship-Timestamp": str(now_ts),
        },
    )
    assert bad_resp.status_code == 401

    # 2. Expired timestamp (> 300s old) is rejected as replay attack
    stale_ts = now_ts - 500
    stale_sig = compute_webhook_signature(payload_bytes, secret, stale_ts)
    stale_resp = await client.post(
        "/api/v1/webhooks/inbound",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Relationship-Signature": stale_sig,
            "X-Relationship-Timestamp": str(stale_ts),
        },
    )
    assert stale_resp.status_code == 401

    # 3. Valid signature & fresh timestamp succeeds
    good_resp = await client.post(
        "/api/v1/webhooks/inbound",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Relationship-Signature": valid_sig,
            "X-Relationship-Timestamp": str(now_ts),
        },
    )
    assert good_resp.status_code == 200
    data = good_resp.json()
    assert data["status"] == "success"
    assert "message_id" in data
    assert data["sequence_number"] > 0
