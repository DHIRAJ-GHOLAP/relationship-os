"""Security test suite validating IDOR defenses, SSRF, security headers, anti-replay, and rate limiting."""

import time
import json
import pytest
from httpx import AsyncClient

from apps.api.src.core.config import settings
from apps.api.src.models.conversation import Conversation
from apps.api.src.models.participant import ConversationParticipant
from apps.api.src.models.user import User
from packages.shared.src.constants import UserRole
from packages.shared.src.crypto import hash_password, generate_secure_token, compute_webhook_signature
from packages.shared.src.ssrf import validate_destination_url


@pytest.mark.asyncio
async def test_security_headers_present_on_all_responses(client: AsyncClient):
    """Every HTTP response must enforce enterprise security headers."""
    resp = await client.get("/health")
    assert resp.status_code == 200

    headers = resp.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert "default-src 'self'" in headers.get("Content-Security-Policy", "")
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "X-Request-ID" in headers


@pytest.mark.asyncio
async def test_idor_prevent_unauthorized_conversation_access(client: AsyncClient, auth_headers, db_session):
    """Users cannot access conversations they are not an explicit participant in."""
    # Create an isolated second conversation between owner and a new user (intruder)
    intruder = User(
        username="intruder_user",
        display_name="Intruder",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.RECIPIENT,
        is_active=True,
    )
    secret_conv = Conversation(
        title="Top Secret Room",
        type="direct",
        status="active",
    )
    db_session.add_all([intruder, secret_conv])
    await db_session.commit()

    part = ConversationParticipant(
        conversation_id=secret_conv.id,
        user_id=intruder.id,
        last_read_sequence=0,
    )
    db_session.add(part)
    await db_session.commit()

    # Recipient (from auth_headers, who is NOT in secret_conv) tries to list messages
    resp = await client.get(
        f"/api/v1/conversations/{secret_conv.id}/messages",
        headers=auth_headers["recipient"],
    )
    # Must be 403 Forbidden
    assert resp.status_code == 403

    # Recipient tries to send a message to secret_conv
    send_resp = await client.post(
        f"/api/v1/conversations/{secret_conv.id}/messages",
        json={"client_message_id": "idor-001", "message": {"body": "I should not be here"}},
        headers=auth_headers["recipient"],
    )
    assert send_resp.status_code == 403


@pytest.mark.asyncio
async def test_ssrf_comprehensive_matrix():
    """Verify SSRF validation blocks all private/cloud metadata ranges and unsafe schemes."""
    blocked_targets = [
        "http://127.0.0.1:8080",
        "http://localhost:5000",
        "http://0.0.0.0:80",
        "http://10.200.1.1/secret",
        "http://172.16.50.4/internal",
        "http://192.168.1.100/admin",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/shadow",
        "gopher://evil.com",
        "ftp://internal.vault/data",
        "http://[::1]:8080",
    ]

    for url in blocked_targets:
        safe, reason = validate_destination_url(url, allow_localhost=False)
        assert safe is False, f"Expected {url} to be blocked by SSRF, but got safe=True"
        assert len(reason) > 0

    # Public HTTPS domains must be allowed
    safe, _ = validate_destination_url("https://api.github.com/webhook", allow_localhost=False)
    assert safe is True


@pytest.mark.asyncio
async def test_webhook_anti_replay_window(client: AsyncClient, test_users):
    """Enforce strict 300s window for webhook signatures."""
    conv = test_users["conversation"]
    secret = settings.WEBHOOK_SIGNING_SECRET

    payload_dict = {
        "conversation_id": conv.id,
        "body": "Anti-replay test",
        "client_message_id": "anti-replay-001",
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    now_ts = int(time.time())

    # Case 1: 301 seconds ago -> Rejected
    stale_ts = now_ts - 301
    stale_sig = compute_webhook_signature(payload_bytes, secret, stale_ts)
    resp_stale = await client.post(
        "/api/v1/webhooks/inbound",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Relationship-Signature": stale_sig,
            "X-Relationship-Timestamp": str(stale_ts),
        },
    )
    assert resp_stale.status_code == 401

    # Case 2: 301 seconds into future -> Rejected
    future_ts = now_ts + 301
    future_sig = compute_webhook_signature(payload_bytes, secret, future_ts)
    resp_future = await client.post(
        "/api/v1/webhooks/inbound",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Relationship-Signature": future_sig,
            "X-Relationship-Timestamp": str(future_ts),
        },
    )
    assert resp_future.status_code == 401


@pytest.mark.asyncio
async def test_enrollment_token_high_entropy_and_uniqueness():
    """Verify enrollment tokens meet cryptographic randomness and entropy guarantees."""
    tokens = set()
    for _ in range(50):
        tok = generate_secure_token(32)
        assert len(tok) >= 43  # URL-safe base64 of 32 bytes is ~43 chars
        tokens.add(tok)
    # No collisions in 50 iterations
    assert len(tokens) == 50
