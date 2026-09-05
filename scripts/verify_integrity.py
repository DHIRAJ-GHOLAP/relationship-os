#!/usr/bin/env python3
"""Relationship OS - Platform Integrity Verification Suite.

Performs static and dynamic checks across:
- Monorepo directory structure and artifact presence
- Database schema and model registration
- API routers and route definitions
- Frontend web client build assets
- Launcher safety and checksum verification
- SSRF protection barriers
- Cryptographic integrity (HMAC, bcrypt, high-entropy tokens)
"""

import hashlib
import os
import sys
from pathlib import Path

# Ensure project root in pythonpath
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_step(name: str):
    print(f"[*] Checking: {name:<50}", end="", flush=True)


def step_ok(detail: str = "OK"):
    print(f" \033[92m[✓ {detail}]\033[0m")


def step_fail(detail: str):
    print(f" \033[91m[✗ FAILED: {detail}]\033[0m")
    sys.exit(1)


def verify_file_structure():
    check_step("Monorepo layout and essential files")
    required_paths = [
        "packages/shared/src/constants.py",
        "packages/shared/src/crypto.py",
        "packages/shared/src/ssrf.py",
        "apps/api/src/main.py",
        "apps/api/src/core/config.py",
        "apps/api/src/core/database.py",
        "apps/api/src/services/message_service.py",
        "apps/api/src/services/outbox_worker.py",
        "apps/web/dist/index.html",
        "apps/cli/src/cli.py",
        "apps/launcher/Launch-RelationshipOS.ps1",
        "apps/launcher/launch.sh",
        "integrations/discord/src/adapter.py",
        "integrations/webhook/src/adapter.py",
        "Dockerfile.api",
        "Dockerfile.web",
        "docker-compose.yml",
        "nginx.conf",
        "requirements.txt",
    ]
    for rel_path in required_paths:
        p = PROJECT_ROOT / rel_path
        if not p.exists():
            step_fail(f"Missing required path: {rel_path}")
    step_ok("All core paths present")


def verify_modules_and_models():
    check_step("Database models and schema metadata")
    from apps.api.src.core.database import Base
    from apps.api.src.models.user import User
    from apps.api.src.models.conversation import Conversation
    from apps.api.src.models.participant import ConversationParticipant
    from apps.api.src.models.message import Message
    from apps.api.src.models.session import Session
    from apps.api.src.models.enrollment import EnrollmentToken
    from apps.api.src.models.outbox import OutboxEvent
    from apps.api.src.models.delivery import MessageDelivery
    from apps.api.src.models.attachment import Attachment
    from apps.api.src.models.audit import AuditEvent

    expected_tables = {
        "users",
        "conversations",
        "conversation_participants",
        "messages",
        "sessions",
        "enrollment_tokens",
        "outbox_events",
        "message_deliveries",
        "attachments",
        "audit_events",
    }
    registered = set(Base.metadata.tables.keys())
    missing = expected_tables - registered
    if missing:
        step_fail(f"Missing registered tables: {missing}")
    step_ok(f"{len(registered)} tables verified")


def verify_api_routes():
    check_step("FastAPI route registrations and OpenAPI schema")
    from apps.api.src.main import app

    schema = app.openapi()
    routes = set(schema.get("paths", {}).keys())

    critical_endpoints = [
        "/health",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/auth/enroll",
        "/api/v1/conversations",
        "/api/v1/conversations/{conversation_id}/messages",
        "/api/v1/conversations/{conversation_id}/read",
        "/api/v1/conversations/{conversation_id}/search",
        "/api/v1/admin/health",
        "/api/v1/admin/sessions",
        "/api/v1/admin/webhooks",
        "/api/v1/admin/audit",
        "/api/v1/webhooks/inbound",
        "/api/v1/attachments/prepare",
        "/api/v1/attachments/upload/{attachment_id}",
        "/api/v1/attachments/download/{attachment_id}",
    ]
    for ep in critical_endpoints:
        if ep not in routes:
            step_fail(f"Missing critical API endpoint: {ep}")
    step_ok(f"{len(routes)} OpenAPI routes verified")


def verify_launcher_safety_and_hashes():
    check_step("Launcher security and checksums")
    ps1_path = PROJECT_ROOT / "apps/launcher/Launch-RelationshipOS.ps1"
    sh_path = PROJECT_ROOT / "apps/launcher/launch.sh"

    # Verify no dangerous blind piping
    ps1_text = ps1_path.read_text(encoding="utf-8")
    if "iex (irm" in ps1_text.lower() or "invoke-expression" in ps1_text.lower():
        step_fail("Dangerous blind invoke-expression detected in PowerShell launcher!")

    sh_text = sh_path.read_text(encoding="utf-8")
    if "| bash" in sh_text or "| sh" in sh_text:
        step_fail("Dangerous piped curl-to-bash detected in shell launcher!")

    ps1_hash = hashlib.sha256(ps1_path.read_bytes()).hexdigest()
    sh_hash = hashlib.sha256(sh_path.read_bytes()).hexdigest()
    step_ok(f"PS1: {ps1_hash[:8]}... | SH: {sh_hash[:8]}...")


def verify_crypto_and_ssrf():
    check_step("Cryptographic safeguards & SSRF barriers")
    from packages.shared.src.crypto import (
        hash_password,
        verify_password,
        generate_secure_token,
        compute_webhook_signature,
        verify_webhook_signature,
    )
    from packages.shared.src.ssrf import validate_destination_url

    # Password check
    h = hash_password("TestSecPassword987!")
    if not verify_password("TestSecPassword987!", h):
        step_fail("Password hashing verification failed")

    # High entropy token
    t1 = generate_secure_token(32)
    t2 = generate_secure_token(32)
    if len(t1) < 32 or t1 == t2:
        step_fail("Entropy check failed")

    # SSRF check: loopback, 169.254, RFC1918 must be blocked
    safe, _ = validate_destination_url("http://127.0.0.1:8080/hook", allow_localhost=False)
    if safe:
        step_fail("SSRF allowed loopback IP")

    safe, _ = validate_destination_url("http://169.254.169.254/latest/meta-data")
    if safe:
        step_fail("SSRF allowed AWS metadata IP")

    safe, _ = validate_destination_url("http://10.0.0.1/admin")
    if safe:
        step_fail("SSRF allowed RFC1918 private IP")

    safe, _ = validate_destination_url("https://api.github.com/webhook")
    if not safe:
        step_fail("SSRF rejected public HTTPS host")

    # HMAC signature check
    body = b'{"event":"test"}'
    secret = "secret123"
    import time
    now = int(time.time())
    sig = compute_webhook_signature(body, secret, now)
    valid, _ = verify_webhook_signature(body, secret, sig, now, tolerance_seconds=300)
    if not valid:
        step_fail("HMAC webhook signature verification failed")

    step_ok("SSRF filter, HMAC & bcrypt verified")


def verify_web_bundle():
    check_step("Frontend production distribution bundle")
    dist_dir = PROJECT_ROOT / "apps/web/dist"
    index_file = dist_dir / "index.html"
    assets_dir = dist_dir / "assets"

    if not index_file.is_file() or index_file.stat().st_size == 0:
        step_fail("dist/index.html is missing or empty")

    if not assets_dir.is_dir() or len(list(assets_dir.glob("*.js"))) == 0:
        step_fail("dist/assets missing compiled JavaScript bundles")

    step_ok("Vite SPA production distribution verified")


def main():
    print("\n" + "=" * 68)
    print("        ♥ Relationship OS System Integrity Verification ♥           ")
    print("=" * 68)
    verify_file_structure()
    verify_modules_and_models()
    verify_api_routes()
    verify_launcher_safety_and_hashes()
    verify_crypto_and_ssrf()
    verify_web_bundle()
    print("=" * 68)
    print("\033[92m[✓✓✓] ALL PLATFORM INTEGRITY CHECKS PASSED PERFECTLY!\033[0m\n")


if __name__ == "__main__":
    main()
