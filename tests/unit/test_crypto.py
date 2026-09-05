"""Unit tests for cryptographic functions, HMAC signing, and replay defense."""

import time
import pytest
from packages.shared.src.crypto import (
    compute_webhook_signature,
    generate_secure_token,
    hash_password,
    hash_token,
    verify_password,
    verify_webhook_signature,
)


def test_password_hashing_and_verification():
    raw_pass = "SuperSecretPassword123!@#"
    hashed = hash_password(raw_pass)
    assert hashed != raw_pass
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    assert verify_password(raw_pass, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


def test_secure_token_generation():
    t1 = generate_secure_token(32)
    t2 = generate_secure_token(32)
    assert len(t1) >= 40  # Base64 encoded 32 bytes
    assert t1 != t2


def test_token_hashing_deterministic():
    token = "fixed_test_token_12345"
    h1 = hash_token(token)
    h2 = hash_token(token)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex string


def test_webhook_hmac_signature_verification_success():
    secret = "whsec_test_secret_key_123"
    payload = b'{"event":"message.created","body":"hello"}'
    now = int(time.time())

    sig = compute_webhook_signature(payload, secret, now)
    assert sig.startswith("v1=")

    valid, reason = verify_webhook_signature(
        payload_bytes=payload,
        secret=secret,
        signature_header=sig,
        timestamp=now,
        tolerance_seconds=300,
    )
    assert valid is True
    assert reason == "Valid"


def test_webhook_hmac_tampered_payload_fails():
    secret = "whsec_test_secret_key_123"
    payload = b'{"event":"message.created","body":"hello"}'
    now = int(time.time())

    sig = compute_webhook_signature(payload, secret, now)

    tampered_payload = b'{"event":"message.created","body":"tampered"}'
    valid, reason = verify_webhook_signature(
        payload_bytes=tampered_payload,
        secret=secret,
        signature_header=sig,
        timestamp=now,
        tolerance_seconds=300,
    )
    assert valid is False
    assert "Signature mismatch" in reason


def test_webhook_hmac_replay_attack_tolerance_fails():
    secret = "whsec_test_secret_key_123"
    payload = b'{"event":"message.created","body":"hello"}'
    stale_timestamp = int(time.time()) - 400  # 400 seconds in past

    sig = compute_webhook_signature(payload, secret, stale_timestamp)

    valid, reason = verify_webhook_signature(
        payload_bytes=payload,
        secret=secret,
        signature_header=sig,
        timestamp=stale_timestamp,
        tolerance_seconds=300,
    )
    assert valid is False
    assert "replay attack prevention" in reason
