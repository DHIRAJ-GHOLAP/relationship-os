"""WebSocket Real-Time Client for Relationship OS with auto-reconnect and sequence replay."""

import asyncio
import json
import logging
import random
from typing import Callable, Dict, Optional
import websockets

logger = logging.getLogger("relationship_os.sdk.ws")


class RelationshipOSWebSocket:
    def __init__(
        self,
        ws_url: str,
        token: str,
        conversation_id: str,
        on_message: Optional[Callable[[Dict], None]] = None,
        on_replay: Optional[Callable[[Dict], None]] = None,
        on_presence: Optional[Callable[[Dict], None]] = None,
        on_status_change: Optional[Callable[[str], None]] = None,
    ):
        self.ws_url = ws_url.rstrip("/")
        self.token = token
        self.conversation_id = conversation_id
        self.on_message = on_message
        self.on_replay = on_replay
        self.on_presence = on_presence
        self.on_status_change = on_status_change

        self.last_known_sequence = 0
        self._running = False
        self._ws = None
        self._main_task = None
        self._ping_task = None

    def start(self):
        self._running = True
        self._main_task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        if self._ping_task:
            self._ping_task.cancel()
        if self._ws:
            await self._ws.close()
        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass
        self._notify_status("DISCONNECTED")

    def _notify_status(self, status: str):
        if self.on_status_change:
            try:
                self.on_status_change(status)
            except Exception:
                pass

    async def send_chat_message(self, body: str, client_message_id: str):
        """Send message frame over active WebSocket."""
        if not self._ws:
            raise ConnectionError("WebSocket is not connected")
        frame = {
            "action": "send",
            "payload": {
                "conversation_id": self.conversation_id,
                "client_message_id": client_message_id,
                "body": body,
            },
        }
        await self._ws.send(json.dumps(frame))

    async def mark_read(self, sequence: int):
        if self._ws:
            frame = {
                "action": "read",
                "payload": {
                    "conversation_id": self.conversation_id,
                    "last_read_sequence": sequence,
                }
            }
            await self._ws.send(json.dumps(frame))

    async def _ping_loop(self):
        while self._running and self._ws:
            try:
                await asyncio.sleep(20)
                if self._ws:
                    await self._ws.send(json.dumps({"action": "ping"}))
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def _run(self):
        reconnect_delay = 1.0
        max_reconnect_delay = 30.0

        while self._running:
            try:
                self._notify_status("CONNECTING")
                url_with_token = f"{self.ws_url}/api/v1/ws?token={self.token}"

                async with websockets.connect(url_with_token, ping_interval=None) as ws:
                    self._ws = ws
                    self._notify_status("AUTHENTICATED")
                    reconnect_delay = 1.0

                    # 1. Send sync frame to request missed events replay
                    self._notify_status("SYNCING")
                    sync_frame = {
                        "action": "sync",
                        "payload": {
                            "conversation_id": self.conversation_id,
                            "last_sequence": self.last_known_sequence,
                        },
                    }
                    await ws.send(json.dumps(sync_frame))

                    # 2. Launch background ping loop
                    if self._ping_task:
                        self._ping_task.cancel()
                    self._ping_task = asyncio.create_task(self._ping_loop())

                    self._notify_status("CONNECTED")

                    # 3. Process inbound messages
                    async for raw_message in ws:
                        try:
                            msg = json.loads(raw_message)
                            mtype = msg.get("type")

                            if mtype == "event":
                                payload = msg.get("payload", {})
                                seq = payload.get("sequence_number", 0)
                                if seq > self.last_known_sequence:
                                    self.last_known_sequence = seq
                                if self.on_message:
                                    self.on_message(payload)

                            elif mtype == "replay":
                                payload = msg.get("payload", {})
                                msgs = payload.get("messages", [])
                                for m in msgs:
                                    seq = m.get("sequence_number", 0)
                                    if seq > self.last_known_sequence:
                                        self.last_known_sequence = seq
                                if self.on_replay:
                                    self.on_replay(payload)

                            elif mtype == "presence":
                                if self.on_presence:
                                    self.on_presence(msg.get("payload", {}))

                            elif mtype == "error":
                                logger.error("WebSocket server error: %s", msg.get("payload"))

                        except Exception as e:
                            logger.warning("Error processing WS frame: %s", str(e))

            except (websockets.ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                self._ws = None
                if not self._running:
                    break
                self._notify_status("RECONNECTING")
                # Exponential backoff with jitter
                sleep_time = reconnect_delay + random.uniform(0.1, 1.0)
                logger.info("WS connection lost (%s). Reconnecting in %.1fs...", str(e), sleep_time)
                await asyncio.sleep(sleep_time)
                reconnect_delay = min(max_reconnect_delay, reconnect_delay * 2)

            except Exception as e:
                self._ws = None
                if not self._running:
                    break
                self._notify_status("ERROR")
                await asyncio.sleep(2.0)
