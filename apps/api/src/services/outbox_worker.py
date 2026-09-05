"""Durable Outbox Event Processor and Integration Router."""

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.core.config import settings
from apps.api.src.core.database import AsyncSessionLocal
from apps.api.src.models.outbox import OutboxEvent
from apps.api.src.models.delivery import MessageDelivery
from apps.api.src.models.webhook import WebhookEndpoint
from packages.shared.src.constants import DeliveryState, EventType
from packages.shared.src.models import CanonicalMessageEvent
from integrations.discord.src.adapter import DiscordAdapter
from integrations.webhook.src.adapter import WebhookAdapter
from integrations.signal.src.adapter import SignalAdapter

logger = logging.getLogger("relationship_os.outbox")


class IntegrationRouter:
    """Dispatches canonical events to all active integration adapters."""
    def __init__(
        self,
        discord: Optional[DiscordAdapter] = None,
        webhook: Optional[WebhookAdapter] = None,
        signal: Optional[SignalAdapter] = None,
    ):
        self.discord = discord or DiscordAdapter()
        self.webhook = webhook or WebhookAdapter()
        self.signal = signal or SignalAdapter()

    async def route_event(self, db: AsyncSession, event: CanonicalMessageEvent) -> List[dict]:
        """Deliver event to all eligible integrations and update MessageDelivery rows."""
        results = []

        # 1. Discord Delivery
        if settings.DISCORD_ENABLED and event.origin != "discord":
            success, ext_id, err = await self.discord.send(event)
            results.append({
                "integration": "discord",
                "success": success,
                "external_id": ext_id,
                "error": err,
            })
            await self._update_delivery(
                db, event.message_id, "discord", success, ext_id, err
            )

        # 2. Configured Database Webhooks
        webhook_query = await db.execute(
            select(WebhookEndpoint).where(WebhookEndpoint.enabled == True)
        )
        endpoints = webhook_query.scalars().all()

        for ep in endpoints:
            # Check event filters
            try:
                filters = json.loads(ep.event_filters_json)
            except Exception:
                filters = ["message.created"]

            event_type_str = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
            if event_type_str in filters or "*" in filters:
                # Deliver to endpoint using endpoint secret or global secret
                secret = settings.WEBHOOK_SIGNING_SECRET
                success, ext_id, err = await self.webhook.send_to_endpoint(
                    url=ep.url,
                    secret=secret,
                    event=event,
                    allow_localhost=settings.WEBHOOK_ALLOW_LOCALHOST,
                )
                results.append({
                    "integration": f"webhook:{ep.name}",
                    "success": success,
                    "external_id": ext_id,
                    "error": err,
                })
                # Update endpoint tracking
                if success:
                    ep.last_success_at = datetime.now(timezone.utc)
                else:
                    ep.last_failure_at = datetime.now(timezone.utc)
                    ep.last_failure_reason = err

                await self._update_delivery(
                    db, event.message_id, f"webhook:{ep.name}", success, ext_id, err
                )

        # 3. Signal Delivery (optional)
        if settings.SIGNAL_ENABLED:
            success, ext_id, err = await self.signal.send(event)
            results.append({
                "integration": "signal",
                "success": success,
                "external_id": ext_id,
                "error": err,
            })
            await self._update_delivery(
                db, event.message_id, "signal", success, ext_id, err
            )

        return results

    async def _update_delivery(
        self,
        db: AsyncSession,
        message_id: str,
        integration_type: str,
        success: bool,
        ext_id: Optional[str],
        error_msg: Optional[str],
    ) -> None:
        query = await db.execute(
            select(MessageDelivery).where(
                MessageDelivery.message_id == message_id,
                MessageDelivery.integration_type == integration_type,
            )
        )
        delivery = query.scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if not delivery:
            delivery = MessageDelivery(
                message_id=message_id,
                integration_type=integration_type,
                attempt_count=0,
                first_attempted_at=now,
            )
            db.add(delivery)

        delivery.attempt_count += 1
        delivery.last_attempted_at = now
        if not delivery.first_attempted_at:
            delivery.first_attempted_at = now

        if success:
            delivery.status = DeliveryState.DELIVERED.value
            delivery.completed_at = now
            delivery.external_message_id = ext_id
            delivery.failure_reason = None
        else:
            delivery.status = DeliveryState.FAILED.value
            delivery.failure_reason = error_msg

        await db.flush()

    async def close(self):
        await self.discord.close()
        await self.webhook.close()
        await self.signal.close()


class OutboxWorker:
    """Background worker that continuously drains pending outbox events."""
    def __init__(self, poll_interval: float = 1.0, router: Optional[IntegrationRouter] = None):
        self.poll_interval = poll_interval
        self.router = router or IntegrationRouter()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("Outbox worker started.")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.router.close()
        logger.info("Outbox worker stopped.")

    async def process_batch(self, batch_size: int = 20) -> int:
        """Process up to batch_size pending outbox events."""
        async with AsyncSessionLocal() as session:
            now = datetime.now(timezone.utc)
            # Find events ready for execution
            query = (
                select(OutboxEvent)
                .where(
                    OutboxEvent.status.in_(["pending", "retrying"]),
                    OutboxEvent.next_attempt_at <= now,
                )
                .order_by(OutboxEvent.created_at.asc())
                .limit(batch_size)
            )
            events = (await session.execute(query)).scalars().all()
            if not events:
                return 0

            processed_count = 0
            for event in events:
                event_id = event.id
                # Lock row
                event.status = "processing"
                event.locked_at = now
                await session.flush()

                try:
                    event_data = json.loads(event.payload_json)
                    canonical_event = CanonicalMessageEvent.model_validate(event_data)
                    results = await self.router.route_event(session, canonical_event)

                    # Check overall success across active deliveries
                    failures = [r for r in results if not r["success"]]
                    if not failures:
                        event.status = "delivered"
                        event.completed_at = datetime.now(timezone.utc)
                        event.error_message = None
                    else:
                        event.retry_count += 1
                        reasons = "; ".join([f"{f['integration']}: {f['error']}" for f in failures])
                        event.error_message = reasons

                        if event.retry_count >= event.max_retries:
                            event.status = "failed"  # Dead letter queue
                            logger.error("Outbox event %s moved to dead-letter (failed after %s attempts): %s",
                                         event_id, event.retry_count, reasons)
                        else:
                            event.status = "retrying"
                            # Exponential backoff with jitter
                            backoff = min(300, (2 ** event.retry_count) + random.uniform(0.1, 1.5))
                            event.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
                            logger.warning("Outbox event %s failed, retrying in %.1fs (attempt %s): %s",
                                           event_id, backoff, event.retry_count, reasons)

                    await session.commit()
                    processed_count += 1

                except Exception as e:
                    await session.rollback()
                    logger.error("Unexpected error processing outbox event %s: %s", event_id, str(e), exc_info=True)
                    # Re-acquire session to mark error
                    async with AsyncSessionLocal() as err_session:
                        evt = (await err_session.execute(select(OutboxEvent).where(OutboxEvent.id == event_id))).scalar_one_or_none()
                        if evt:
                            evt.retry_count += 1
                            evt.status = "retrying" if evt.retry_count < evt.max_retries else "failed"
                            evt.error_message = str(e)
                            evt.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=10)
                            await err_session.commit()

            return processed_count

    async def _run_loop(self):
        while self._running:
            try:
                processed = await self.process_batch(batch_size=25)
                if processed == 0:
                    await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Outbox worker loop error: %s", str(e), exc_info=True)
                await asyncio.sleep(self.poll_interval)
