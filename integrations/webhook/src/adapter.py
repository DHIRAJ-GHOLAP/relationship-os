"""Generic secure webhook integration adapter for Relationship OS."""

import time
import json
import logging
from typing import Any, Dict, Optional, Tuple
import httpx

from integrations.base import IntegrationAdapter
from apps.api.src.core.config import settings
from packages.shared.src.crypto import compute_webhook_signature
from packages.shared.src.ssrf import validate_destination_url
from packages.shared.src.models import CanonicalMessageEvent

logger = logging.getLogger("relationship_os.integrations.webhook")


class WebhookAdapter(IntegrationAdapter):
    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client or httpx.AsyncClient(timeout=float(settings.WEBHOOK_TIMEOUT_SECONDS))

    @property
    def name(self) -> str:
        return "webhook"

    async def validate_config(self) -> Tuple[bool, str]:
        if not settings.WEBHOOK_ENABLED:
            return False, "Webhook integration is disabled in configuration"
        if not settings.WEBHOOK_SIGNING_SECRET:
            return False, "WEBHOOK_SIGNING_SECRET is missing"
        return True, "Configured"

    async def send_to_endpoint(
        self,
        url: str,
        secret: str,
        event: CanonicalMessageEvent,
        allow_localhost: bool = False,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Deliver payload to a specific webhook endpoint with SSRF check and HMAC signature."""
        # SSRF Defense
        safe, reason = validate_destination_url(url, allow_localhost=allow_localhost or settings.WEBHOOK_ALLOW_LOCALHOST)
        if not safe:
            logger.warning("SSRF blocked attempt to webhook URL %s: %s", url, reason)
            return False, None, f"SSRF Blocked: {reason}"

        payload_bytes = event.model_dump_json().encode("utf-8")
        timestamp = int(time.time())
        signature = compute_webhook_signature(payload_bytes, secret, timestamp)

        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"{settings.APP_NAME}-Webhook/{settings.APP_VERSION}",
            "X-Relationship-Signature": signature,
            "X-Relationship-Timestamp": str(timestamp),
            "X-Relationship-Event": event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
            "X-Relationship-Event-ID": event.event_id,
        }

        try:
            resp = await self._client.post(url, content=payload_bytes, headers=headers)
            # Bound response reading to prevent memory exhaustion
            response_text = resp.text[:1000]

            if resp.status_code in (200, 201, 202, 204):
                return True, f"webhook_ack_{resp.status_code}", None
            elif resp.status_code == 429:
                return False, None, f"Webhook endpoint rate limited (HTTP 429): {response_text}"
            elif resp.status_code >= 500:
                return False, None, f"Webhook remote server error (HTTP {resp.status_code}): {response_text}"
            else:
                return False, None, f"Webhook rejected payload (HTTP {resp.status_code}): {response_text}"

        except httpx.TimeoutException:
            return False, None, "Webhook delivery timed out (transient)"
        except httpx.RequestError as e:
            return False, None, f"Webhook network error: {str(e)}"
        except Exception as e:
            return False, None, f"Unexpected webhook error: {str(e)}"

    async def send(self, event: CanonicalMessageEvent) -> Tuple[bool, Optional[str], Optional[str]]:
        # Default implementation for global webhook config if configured
        valid, _ = await self.validate_config()
        if not valid:
            return True, "skipped_disabled", None
        return True, "webhook_router_managed", None

    async def health_check(self) -> Dict[str, Any]:
        valid, msg = await self.validate_config()
        return {
            "name": self.name,
            "enabled": settings.WEBHOOK_ENABLED,
            "valid": valid,
            "message": msg,
        }

    async def close(self) -> None:
        await self._client.aclose()
