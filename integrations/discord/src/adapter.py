"""Discord integration adapter for Relationship OS."""

import re
import logging
from typing import Any, Dict, Optional, Tuple
import httpx

from integrations.base import IntegrationAdapter
from apps.api.src.core.config import settings
from packages.shared.src.models import CanonicalMessageEvent

logger = logging.getLogger("relationship_os.integrations.discord")


def sanitize_discord_content(text: str) -> str:
    """Escape mentions to prevent accidental @everyone / @here or role pings."""
    sanitized = text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
    sanitized = re.sub(r"<@&?[0-9]+>", "[mention redacted]", sanitized)
    return sanitized


class DiscordAdapter(IntegrationAdapter):
    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client or httpx.AsyncClient(timeout=10.0)

    @property
    def name(self) -> str:
        return "discord"

    async def validate_config(self) -> Tuple[bool, str]:
        if not settings.DISCORD_ENABLED:
            return False, "Discord integration is disabled in configuration"
        if not settings.discord_bot_tokens and not settings.DISCORD_WEBHOOK_URL:
            return False, "Neither DISCORD_BOT_TOKEN nor DISCORD_WEBHOOK_URL is configured"
        return True, "Configured"

    async def send(self, event: CanonicalMessageEvent) -> Tuple[bool, Optional[str], Optional[str]]:
        # Loop prevention: Do not echo messages originating from Discord back to Discord
        if event.origin == "discord":
            logger.info("Loop prevention: Skipping Discord delivery for event originating from discord.")
            return True, "skipped_loop_prevention", None

        valid, reason = await self.validate_config()
        if not valid:
            return False, None, f"Configuration invalid: {reason}"

        sender_name = event.sender_name or "Recipient"
        sanitized_body = sanitize_discord_content(event.message.body)

        content = (
            f"**[{settings.ROOM_NAME}]**\n"
            f"**From:** {sender_name} (Seq: #{event.sequence})\n"
            f"```\n{sanitized_body}\n```"
        )

        # 1. Preferred: Discord Webhook if configured
        if settings.DISCORD_WEBHOOK_URL:
            try:
                resp = await self._client.post(
                    settings.DISCORD_WEBHOOK_URL,
                    json={
                        "content": content,
                        "username": settings.APP_NAME,
                        "allowed_mentions": {"parse": []}
                    },
                )
                if resp.status_code in (200, 201, 204):
                    try:
                        ext_id = str(resp.json().get("id", "discord_webhook_ok"))
                    except Exception:
                        ext_id = "discord_webhook_ok"
                    return True, ext_id, None
                logger.warning(f"Discord webhook failed with HTTP {resp.status_code}. Failing over to bot pool...")
            except Exception as e:
                logger.warning(f"Discord webhook error: {e}. Failing over to bot pool...")

        # 2. Multi-bot failover pool
        bot_tokens = settings.discord_bot_tokens
        if not bot_tokens:
            return False, None, "No bot tokens configured and webhook unavailable"

        if not settings.DISCORD_CHANNEL_ID:
            return False, None, "Missing DISCORD_CHANNEL_ID for bot channel delivery"

        last_error = None
        for idx, token in enumerate(bot_tokens):
            url = f"https://discord.com/api/v10/channels/{settings.DISCORD_CHANNEL_ID}/messages"
            headers = {
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
            }
            try:
                resp = await self._client.post(
                    url,
                    headers=headers,
                    json={
                        "content": content,
                        "allowed_mentions": {"parse": []}
                    },
                )
                if resp.status_code in (200, 201, 204):
                    try:
                        ext_id = str(resp.json().get("id", f"discord_bot_{idx}_ok"))
                    except Exception:
                        ext_id = f"discord_bot_{idx}_ok"
                    if idx > 0:
                        logger.info(f"Delivered message to Discord via backup bot #{idx + 1}.")
                    return True, ext_id, None
                else:
                    last_error = f"Bot #{idx + 1} rejected with HTTP {resp.status_code}"
                    logger.warning(f"{last_error}. Failing over to next bot in pool...")
            except httpx.TimeoutException:
                last_error = f"Bot #{idx + 1} timed out"
                logger.warning(f"{last_error}. Failing over to next bot in pool...")
            except httpx.RequestError as e:
                last_error = f"Bot #{idx + 1} network error: {e}"
                logger.warning(f"{last_error}. Failing over to next bot in pool...")
            except Exception as e:
                last_error = f"Bot #{idx + 1} error: {e}"
                logger.warning(f"{last_error}. Failing over to next bot in pool...")

        return False, None, f"All {len(bot_tokens)} Discord bots failed. Last error: {last_error}"

    async def health_check(self) -> Dict[str, Any]:
        valid, msg = await self.validate_config()
        return {
            "name": self.name,
            "enabled": settings.DISCORD_ENABLED,
            "valid": valid,
            "message": msg,
        }

    async def close(self) -> None:
        await self._client.aclose()
