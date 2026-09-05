"""Pluggable Signal integration adapter for Relationship OS."""

import logging
from typing import Any, Dict, Optional, Tuple
import httpx

from integrations.base import IntegrationAdapter
from apps.api.src.core.config import settings
from packages.shared.src.models import CanonicalMessageEvent

logger = logging.getLogger("relationship_os.integrations.signal")


class SignalAdapter(IntegrationAdapter):
    """
    Adapter for communicating via a Signal-compatible REST bridge
    (e.g., signal-cli-rest-api daemon).
    """
    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client or httpx.AsyncClient(timeout=10.0)

    @property
    def name(self) -> str:
        return "signal"

    async def validate_config(self) -> Tuple[bool, str]:
        if not settings.SIGNAL_ENABLED:
            return False, "Signal integration is disabled"
        if not settings.SIGNAL_BRIDGE_URL:
            return False, "SIGNAL_BRIDGE_URL is not set"
        if not settings.SIGNAL_RECIPIENT_NUMBER:
            return False, "SIGNAL_RECIPIENT_NUMBER is not set"
        return True, "Configured"

    async def send(self, event: CanonicalMessageEvent) -> Tuple[bool, Optional[str], Optional[str]]:
        if not settings.SIGNAL_ENABLED:
            return True, "skipped_disabled", None

        valid, reason = await self.validate_config()
        if not valid:
            return False, None, f"Signal config invalid: {reason}"

        body_text = f"[{settings.ROOM_NAME}] {event.sender_name or 'Recipient'}: {event.message.body}"
        endpoint = f"{settings.SIGNAL_BRIDGE_URL.rstrip('/')}/v2/send"
        headers = {}
        if settings.SIGNAL_BRIDGE_TOKEN:
            headers["Authorization"] = f"Bearer {settings.SIGNAL_BRIDGE_TOKEN}"

        try:
            resp = await self._client.post(
                endpoint,
                headers=headers,
                json={
                    "message": body_text,
                    "recipients": [settings.SIGNAL_RECIPIENT_NUMBER],
                },
            )
            if resp.status_code in (200, 201):
                return True, "signal_sent", None
            return False, None, f"Signal bridge error (HTTP {resp.status_code}): {resp.text[:500]}"
        except httpx.TimeoutException:
            return False, None, "Signal bridge timed out (transient)"
        except httpx.RequestError as e:
            return False, None, f"Signal bridge network error: {str(e)}"
        except Exception as e:
            return False, None, f"Unexpected Signal error: {str(e)}"

    async def health_check(self) -> Dict[str, Any]:
        valid, msg = await self.validate_config()
        return {
            "name": self.name,
            "enabled": settings.SIGNAL_ENABLED,
            "valid": valid,
            "message": msg,
        }

    async def close(self) -> None:
        await self._client.aclose()
