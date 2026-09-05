"""Cryptographic helpers for Relationship OS.

Provides secure password hashing, HMAC payload signing for webhooks,
replay attack verification, and high-entropy token generation.
"""

import hmac
import hashlib
import secrets
import time
from typing import Tuple
import bcrypt


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt and automatic salt."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its bcrypt hash in constant time."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception:
        return False


def generate_secure_token(nbytes: int = 32) -> str:
    """Generate a cryptographically secure URL-safe token."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Hash an enrollment or session token using SHA-256 for secure database lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def compute_webhook_signature(payload_bytes: bytes, secret: str, timestamp: int) -> str:
    """
    Compute HMAC-SHA256 signature for webhook payload.
    Signature covers timestamp and raw payload bytes: f"t={timestamp}.{payload}"
    """
    message = f"t={timestamp}.".encode("utf-8") + payload_bytes
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"v1={signature}"


def verify_webhook_signature(
    payload_bytes: bytes,
    secret: str,
    signature_header: str,
    timestamp: int,
    tolerance_seconds: int = 300
) -> Tuple[bool, str]:
    """
    Verify incoming webhook HMAC signature and enforce anti-replay timestamp window.
    Returns (is_valid, reason).
    """
    current_time = int(time.time())
    if abs(current_time - timestamp) > tolerance_seconds:
        return False, "Timestamp outside acceptable tolerance window (replay attack prevention)"

    expected_signature = compute_webhook_signature(payload_bytes, secret, timestamp)
    
    if not hmac.compare_digest(expected_signature, signature_header):
        return False, "Signature mismatch"

    return True, "Valid"
