"""Integration tests for Admin Control Plane API, RBAC, Webhook configuration, and session controls."""

import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient

from apps.api.src.models.delivery import MessageDelivery
from apps.api.src.models.outbox import OutboxEvent
from apps.api.src.models.session import Session


@pytest.mark.asyncio
async def test_admin_rbac_forbidden_for_recipient(client: AsyncClient, auth_headers):
    """Recipient role must be denied access with HTTP 403 to all admin endpoints."""
    # Recipient attempts to access health
    resp = await client.get("/api/v1/admin/health", headers=auth_headers["recipient"])
    assert resp.status_code == 403

    # Recipient attempts to list sessions
    resp2 = await client.get("/api/v1/admin/sessions", headers=auth_headers["recipient"])
    assert resp2.status_code == 403

    # Recipient attempts to list webhooks
    resp3 = await client.get("/api/v1/admin/webhooks", headers=auth_headers["recipient"])
    assert resp3.status_code == 403


@pytest.mark.asyncio
async def test_admin_health_metrics(client: AsyncClient, auth_headers):
    """Owner or Admin can retrieve internal operational health metrics."""
    resp = await client.get("/api/v1/admin/health", headers=auth_headers["owner"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["database"] == "connected"
    assert "outbox" in data
    assert "active_sessions" in data
    assert data["active_sessions"] >= 1
    assert "integrations" in data


@pytest.mark.asyncio
async def test_admin_session_revocation(client: AsyncClient, auth_headers, test_users, db_session):
    """Admin can list and administratively revoke sessions."""
    # List sessions
    list_resp = await client.get("/api/v1/admin/sessions", headers=auth_headers["admin"])
    assert list_resp.status_code == 200
    sessions = list_resp.json()
    assert len(sessions) >= 3

    # Find recipient's session ID
    recipient = test_users["recipient"]
    recip_session = next(s for s in sessions if s["user_id"] == recipient.id)
    session_id = recip_session["id"]

    # Recipient me works
    me1 = await client.get("/api/v1/auth/me", headers=auth_headers["recipient"])
    assert me1.status_code == 200

    # Admin revokes recipient session
    revoke_resp = await client.post(
        f"/api/v1/admin/sessions/{session_id}/revoke",
        headers=auth_headers["admin"],
    )
    assert revoke_resp.status_code == 200

    # Recipient session is now rejected
    me2 = await client.get("/api/v1/auth/me", headers=auth_headers["recipient"])
    assert me2.status_code == 401


@pytest.mark.asyncio
async def test_admin_webhook_crud_and_ssrf(client: AsyncClient, auth_headers):
    """Test webhook registration with SSRF protection, listing with masked secrets, and deletion."""
    # 1. SSRF check: attempt to register AWS metadata URL
    ssrf_resp = await client.post(
        "/api/v1/admin/webhooks",
        json={
            "name": "Evil Hook",
            "url": "http://169.254.169.254/latest/meta-data",
            "event_filters": ["message.created"],
        },
        headers=auth_headers["owner"],
    )
    assert ssrf_resp.status_code == 400

    # 2. Valid external HTTPS webhook registration
    create_resp = await client.post(
        "/api/v1/admin/webhooks",
        json={
            "name": "Production Slack Relay",
            "url": "https://hooks.slack.com/services/T00/B00/XXXX",
            "event_filters": ["message.created"],
            "max_retries": 5,
        },
        headers=auth_headers["owner"],
    )
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    webhook_id = created_data["id"]
    assert "signing_secret" in created_data
    assert created_data["signing_secret"].startswith("whsec_")
    assert "secret_preview" in created_data

    # 3. Listing webhooks returns masked preview, never raw secret
    list_resp = await client.get("/api/v1/admin/webhooks", headers=auth_headers["owner"])
    assert list_resp.status_code == 200
    endpoints = list_resp.json()
    matched = next(ep for ep in endpoints if ep["id"] == webhook_id)
    assert "signing_secret" not in matched
    assert matched["secret_preview"].startswith("whsec_")

    # 4. Deleting webhook
    del_resp = await client.delete(f"/api/v1/admin/webhooks/{webhook_id}", headers=auth_headers["owner"])
    assert del_resp.status_code == 200

    # 5. Deleted webhook no longer in list
    list_resp2 = await client.get("/api/v1/admin/webhooks", headers=auth_headers["owner"])
    assert not any(ep["id"] == webhook_id for ep in list_resp2.json())


@pytest.mark.asyncio
async def test_admin_failed_delivery_inspection_and_retry(client: AsyncClient, auth_headers, db_session, test_users):
    """Test inspecting failed deliveries and triggering retry."""
    # Seed a failed delivery record
    failed_deliv = MessageDelivery(
        id="deliv-failed-99",
        message_id="msg-failed-99",
        integration_type="discord",
        status="failed",
        attempt_count=5,
        failure_reason="Discord API 500 server error",
        last_attempted_at=datetime.now(timezone.utc),
    )
    failed_outbox = OutboxEvent(
        id="outbox-failed-99",
        event_type="message.created",
        payload_json="{}",
        status="failed",
        retry_count=5,
        max_retries=5,
        next_attempt_at=datetime.now(timezone.utc),
    )
    db_session.add_all([failed_deliv, failed_outbox])
    await db_session.commit()

    # List failed deliveries
    resp = await client.get("/api/v1/admin/deliveries/failed", headers=auth_headers["owner"])
    assert resp.status_code == 200
    items = resp.json()
    assert any(d["id"] == "deliv-failed-99" for d in items)

    # Retry delivery
    retry_resp = await client.post(
        "/api/v1/admin/deliveries/deliv-failed-99/retry",
        headers=auth_headers["owner"],
    )
    assert retry_resp.status_code == 200

    # Verify status changed to queued
    db_session.expire_all()
    failed_deliv_reloaded = await db_session.get(MessageDelivery, "deliv-failed-99")
    assert failed_deliv_reloaded.status == "queued"


@pytest.mark.asyncio
async def test_admin_audit_log_inspection(client: AsyncClient, auth_headers):
    """Audit logs record operational events and are retrievable by admin."""
    # Trigger an administrative action that records an audit log
    await client.post(
        "/api/v1/admin/webhooks",
        json={
            "name": "Audit Trigger Hook",
            "url": "https://example.com/audit-webhook",
            "event_filters": ["message.created"],
        },
        headers=auth_headers["owner"],
    )

    resp = await client.get("/api/v1/admin/audit?limit=20", headers=auth_headers["owner"])
    assert resp.status_code == 200
    events = resp.json()
    assert isinstance(events, list)
    assert len(events) >= 1
    assert "action" in events[0]
    assert "actor_id" in events[0]
