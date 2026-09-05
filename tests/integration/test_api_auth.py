"""Integration tests for authentication, enrollment, session management, and role authorization."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_password_login_success(client: AsyncClient, test_users):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "owner_user", "password": "OwnerSecurePass123!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["username"] == "owner_user"
    assert "access_token" in resp.cookies


@pytest.mark.asyncio
async def test_password_login_invalid_credentials_fails(client: AsyncClient, test_users):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "owner_user", "password": "WrongPassword!"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "AUTH_INVALID"


@pytest.mark.asyncio
async def test_get_me_endpoint(client: AsyncClient, auth_headers):
    # Authenticated
    resp = await client.get("/api/v1/auth/me", headers=auth_headers["owner"])
    assert resp.status_code == 200
    assert resp.json()["username"] == "owner_user"

    # Unauthenticated
    resp_unauth = await client.get("/api/v1/auth/me")
    assert resp_unauth.status_code == 401


@pytest.mark.asyncio
async def test_enrollment_token_flow(client: AsyncClient, auth_headers):
    # 1. Owner generates enrollment token for recipient
    resp = await client.post(
        "/api/v1/auth/enrollment-tokens",
        json={"device_name": "PowerShell Surface", "platform": "windows", "expires_in_hours": 24},
        headers=auth_headers["owner"],
    )
    assert resp.status_code == 200
    token = resp.json()["token"]
    assert len(token) > 20

    # 2. Recipient redeems token from unauthenticated device
    redeem_resp = await client.post(
        "/api/v1/auth/enroll",
        json={"token": token, "device_name": "PowerShell Surface", "platform": "windows"},
    )
    assert redeem_resp.status_code == 200
    data = redeem_resp.json()
    assert "access_token" in data
    assert data["user"]["role"] == "RECIPIENT"

    # 3. Re-redeeming used token fails
    reuse_resp = await client.post(
        "/api/v1/auth/enroll",
        json={"token": token, "device_name": "Second Device"},
    )
    assert reuse_resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_session(client: AsyncClient, auth_headers):
    # Verify session works
    me1 = await client.get("/api/v1/auth/me", headers=auth_headers["recipient"])
    assert me1.status_code == 200

    # Logout
    logout_resp = await client.post("/api/v1/auth/logout", headers=auth_headers["recipient"])
    assert logout_resp.status_code == 200

    # Subsequent request using same token must fail
    me2 = await client.get("/api/v1/auth/me", headers=auth_headers["recipient"])
    assert me2.status_code == 401
