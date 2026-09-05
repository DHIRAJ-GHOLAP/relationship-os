"""Client REST SDK for Relationship OS."""

import uuid
from typing import Any, Dict, List, Optional
import httpx


class RelationshipOSClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")
        self.access_token: Optional[str] = None
        self.user_data: Optional[Dict[str, Any]] = None
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=15.0)

    def _auth_headers(self) -> Dict[str, str]:
        headers = {"User-Agent": "RelationshipOS-Client/1.0"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def login(self, username: str, password: str, device_name: str = "CLI Client", platform: str = "linux") -> Dict[str, Any]:
        """Authenticate with credentials and store access token."""
        resp = await self._client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password, "device_name": device_name, "platform": platform},
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        self.user_data = data["user"]
        return data

    async def enroll(self, token: str, device_name: str = "CLI Client", platform: str = "linux") -> Dict[str, Any]:
        """Redeem a one-time enrollment token."""
        resp = await self._client.post(
            "/api/v1/auth/enroll",
            json={"token": token, "device_name": device_name, "platform": platform},
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        self.user_data = data["user"]
        return data

    async def get_me(self) -> Dict[str, Any]:
        resp = await self._client.get("/api/v1/auth/me", headers=self._auth_headers())
        resp.raise_for_status()
        return resp.json()

    async def get_conversations(self) -> List[Dict[str, Any]]:
        resp = await self._client.get("/api/v1/conversations", headers=self._auth_headers())
        resp.raise_for_status()
        return resp.json()

    async def get_history(
        self,
        conversation_id: str,
        before_seq: Optional[int] = None,
        after_seq: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        params = {"limit": limit}
        if before_seq is not None:
            params["before_seq"] = before_seq
        if after_seq is not None:
            params["after_seq"] = after_seq

        resp = await self._client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            params=params,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def send_message(
        self,
        conversation_id: str,
        body: str,
        client_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Idempotently send a message via REST."""
        c_id = client_message_id or str(uuid.uuid4())
        payload = {
            "client_message_id": c_id,
            "message": {"type": "text", "body": body},
        }
        resp = await self._client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json=payload,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def mark_read(self, conversation_id: str, last_read_sequence: int) -> Dict[str, Any]:
        resp = await self._client.post(
            f"/api/v1/conversations/{conversation_id}/read",
            json={"last_read_sequence": last_read_sequence},
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def search_messages(self, conversation_id: str, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        resp = await self._client.get(
            f"/api/v1/conversations/{conversation_id}/search",
            params={"q": query, "limit": limit},
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()
