"""WebSocket real-time transport with authentication, heartbeats, sequence replay, and live broadcast."""

import asyncio
import json
import logging
from typing import Dict, List, Set, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from apps.api.src.core.database import AsyncSessionLocal
from apps.api.src.core.security import decode_access_token
from apps.api.src.models.session import Session
from apps.api.src.models.user import User
from apps.api.src.services.message_service import MessageService
from apps.api.src.services.presence_service import PresenceService
from apps.api.src.services.read_service import ReadService
from packages.shared.src.constants import ErrorCode, EventType, PresenceState, UserRole
from packages.shared.src.models import MessagePayload
from packages.shared.src.utils import ensure_utc

logger = logging.getLogger("relationship_os.ws")
router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections per conversation and handles broadcasts."""
    def __init__(self):
        # conversation_id -> set of (WebSocket, user_id, session_id)
        self.active_rooms: Dict[str, Set[WebSocket]] = {}
        self.socket_metadata: Dict[WebSocket, dict] = {}

    def register(self, conv_id: str, ws: WebSocket, user_id: str, session_id: str, username: str, role: UserRole):
        if conv_id not in self.active_rooms:
            self.active_rooms[conv_id] = set()
        self.active_rooms[conv_id].add(ws)
        self.socket_metadata[ws] = {
            "conversation_id": conv_id,
            "user_id": user_id,
            "session_id": session_id,
            "username": username,
            "role": role,
        }

    def unregister(self, ws: WebSocket) -> Optional[dict]:
        meta = self.socket_metadata.pop(ws, None)
        if meta:
            conv_id = meta["conversation_id"]
            if conv_id in self.active_rooms:
                self.active_rooms[conv_id].discard(ws)
                if not self.active_rooms[conv_id]:
                    del self.active_rooms[conv_id]
        return meta

    async def broadcast_to_room(self, conv_id: str, frame: dict, exclude_ws: Optional[WebSocket] = None):
        """Broadcast a message frame to all active connections in a conversation room."""
        if conv_id not in self.active_rooms:
            return

        dead_sockets = []
        payload_str = json.dumps(frame)

        for ws in list(self.active_rooms[conv_id]):
            if exclude_ws and ws == exclude_ws:
                continue
            try:
                await ws.send_text(payload_str)
            except Exception:
                dead_sockets.append(ws)

        for ws in dead_sockets:
            self.unregister(ws)


ws_manager = ConnectionManager()


@router.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    """
    Main WebSocket real-time endpoint.
    Accepts token via query parameter or initial auth frame.
    """
    await websocket.accept()

    user_data = None

    # Try authenticate via query parameter
    if token:
        try:
            payload = decode_access_token(token)
            async with AsyncSessionLocal() as db:
                sess_query = await db.execute(
                    select(Session).where(Session.id == payload.get("session_id"), Session.is_revoked == False)
                )
                session = sess_query.scalar_one_or_none()
                if session and ensure_utc(session.expires_at) > datetime.now(timezone.utc):
                    user_query = await db.execute(select(User).where(User.id == payload.get("sub")))
                    user = user_query.scalar_one_or_none()
                    if user and user.is_active:
                        user_data = {
                            "user_id": user.id,
                            "session_id": session.id,
                            "username": user.username,
                            "display_name": user.display_name,
                            "role": user.role,
                            "device_name": session.device_name,
                        }
        except Exception as e:
            logger.warning("WS query token authentication failed: %s", str(e))

    # If not authenticated via query, wait for initial auth frame
    if not user_data:
        try:
            init_frame_raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            init_frame = json.loads(init_frame_raw)
            if init_frame.get("action") == "auth":
                auth_token = init_frame.get("payload", {}).get("token")
                payload = decode_access_token(auth_token)
                async with AsyncSessionLocal() as db:
                    sess_query = await db.execute(
                        select(Session).where(Session.id == payload.get("session_id"), Session.is_revoked == False)
                    )
                    session = sess_query.scalar_one_or_none()
                    if session and ensure_utc(session.expires_at) > datetime.now(timezone.utc):
                        user_query = await db.execute(select(User).where(User.id == payload.get("sub")))
                        user = user_query.scalar_one_or_none()
                        if user and user.is_active:
                            user_data = {
                                "user_id": user.id,
                                "session_id": session.id,
                                "username": user.username,
                                "display_name": user.display_name,
                                "role": user.role,
                                "device_name": session.device_name,
                            }
        except Exception as e:
            logger.warning("WS auth frame failed: %s", str(e))

    if not user_data:
        await websocket.send_text(json.dumps({
            "type": "error",
            "payload": {"code": ErrorCode.AUTH_INVALID.value, "message": "Authentication failed"}
        }))
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # User is authenticated
    user_id = user_data["user_id"]
    session_id = user_data["session_id"]
    role = user_data["role"]

    # Resolve default conversation
    async with AsyncSessionLocal() as db:
        # Update user presence to online
        await PresenceService.update_presence(
            db, user_id=user_id, status=PresenceState.ONLINE, device_name=user_data["device_name"]
        )
        await db.commit()

    # Wait for client's subscribe / sync frame or bind to conversation
    current_conv_id = None

    try:
        # Acknowledge successful authentication
        await websocket.send_text(json.dumps({
            "type": "ack",
            "payload": {
                "message": "Authenticated successfully",
                "user_id": user_id,
                "role": role.value if hasattr(role, "value") else str(role),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))

        while True:
            data = await websocket.receive_text()
            frame = json.loads(data)
            action = frame.get("action")
            payload = frame.get("payload", {})

            # 1. Heartbeat / Ping
            if action == "ping":
                async with AsyncSessionLocal() as db:
                    await PresenceService.update_presence(
                        db, user_id=user_id, status=PresenceState.ONLINE, device_name=user_data["device_name"]
                    )
                    await db.commit()
                await websocket.send_text(json.dumps({
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }))
                continue

            # 2. Join & Sync Conversation with Sequence Replay
            elif action == "sync":
                conv_id = payload.get("conversation_id")
                last_seq = payload.get("last_sequence", 0)

                async with AsyncSessionLocal() as db:
                    # Authorize conversation access
                    conv = await MessageService.verify_conversation_access(db, conv_id, user_id, role)
                    current_conv_id = conv.id
                    ws_manager.register(
                        current_conv_id, websocket, user_id, session_id, user_data["username"], role
                    )

                    # Monotonic sequence replay: fetch all messages where sequence_number > last_seq
                    replay_messages = await MessageService.get_history(
                        db, conversation_id=current_conv_id, after_seq=last_seq, limit=100
                    )

                    serialized_msgs = [
                        {
                            "id": m.id,
                            "conversation_id": m.conversation_id,
                            "sender_id": m.sender_id,
                            "message_type": m.message_type,
                            "body": m.body,
                            "sequence_number": m.sequence_number,
                            "delivery_state": m.delivery_state,
                            "created_at": m.created_at.isoformat(),
                            "client_message_id": m.client_message_id,
                        }
                        for m in replay_messages
                    ]

                    await websocket.send_text(json.dumps({
                        "type": "replay",
                        "payload": {
                            "conversation_id": current_conv_id,
                            "messages": serialized_msgs,
                            "count": len(serialized_msgs),
                            "synchronized_up_to": serialized_msgs[-1]["sequence_number"] if serialized_msgs else last_seq,
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }))

                    # Broadcast presence to the room
                    await ws_manager.broadcast_to_room(current_conv_id, {
                        "type": "presence",
                        "payload": {
                            "user_id": user_id,
                            "username": user_data["username"],
                            "status": PresenceState.ONLINE.value,
                        }
                    }, exclude_ws=websocket)

            # 3. Real-Time Message Send
            elif action == "send":
                conv_id = payload.get("conversation_id") or current_conv_id
                client_msg_id = payload.get("client_message_id")
                body = payload.get("body", "")

                if not conv_id or not client_msg_id or not body:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "payload": {"code": ErrorCode.INVALID_REQUEST.value, "message": "Missing required send fields"}
                    }))
                    continue

                async with AsyncSessionLocal() as db:
                    await MessageService.verify_conversation_access(db, conv_id, user_id, role)
                    msg, is_new = await MessageService.send_message(
                        db=db,
                        conversation_id=conv_id,
                        sender_id=user_id,
                        sender_name=user_data["display_name"],
                        sender_role=role,
                        client_message_id=client_msg_id,
                        payload=MessagePayload(body=body),
                        origin="chat",
                    )
                    await db.commit()

                    broadcast_payload = {
                        "id": msg.id,
                        "conversation_id": msg.conversation_id,
                        "sender_id": msg.sender_id,
                        "sender_name": user_data["display_name"],
                        "message_type": msg.message_type,
                        "body": msg.body,
                        "sequence_number": msg.sequence_number,
                        "delivery_state": msg.delivery_state,
                        "created_at": msg.created_at.isoformat(),
                        "client_message_id": msg.client_message_id,
                    }

                # Broadcast to all active clients in room
                await ws_manager.broadcast_to_room(conv_id, {
                    "type": "event",
                    "event_id": msg.id,
                    "event_type": EventType.MESSAGE_CREATED.value,
                    "payload": broadcast_payload,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            # 4. Ephemeral Typing Indicator
            elif action == "typing":
                conv_id = payload.get("conversation_id") or current_conv_id
                if conv_id:
                    is_typing = bool(payload.get("typing", False))
                    await ws_manager.broadcast_to_room(conv_id, {
                        "type": "typing",
                        "payload": {
                            "conversation_id": conv_id,
                            "user_id": user_id,
                            "username": user_data["username"],
                            "is_typing": is_typing,
                        }
                    }, exclude_ws=websocket)

            # 5. Read Receipt
            elif action == "read":
                conv_id = payload.get("conversation_id") or current_conv_id
                last_read_seq = int(payload.get("last_read_sequence", 0))
                if conv_id and last_read_seq > 0:
                    async with AsyncSessionLocal() as db:
                        await ReadService.mark_read(db, conv_id, user_id, last_read_seq)
                        await db.commit()

                    await ws_manager.broadcast_to_room(conv_id, {
                        "type": "read",
                        "payload": {
                            "conversation_id": conv_id,
                            "user_id": user_id,
                            "last_read_sequence": last_read_seq,
                        }
                    }, exclude_ws=websocket)

    except WebSocketDisconnect:
        meta = ws_manager.unregister(websocket)
        if meta and meta.get("conversation_id"):
            conv_id = meta["conversation_id"]
            # Check if user has other connections open
            has_other_conns = any(
                m.get("user_id") == user_id for s, m in ws_manager.socket_metadata.items()
            )
            if not has_other_conns:
                async with AsyncSessionLocal() as db:
                    await PresenceService.update_presence(
                        db, user_id=user_id, status=PresenceState.OFFLINE
                    )
                    await db.commit()

                await ws_manager.broadcast_to_room(conv_id, {
                    "type": "presence",
                    "payload": {
                        "user_id": user_id,
                        "status": PresenceState.OFFLINE.value,
                    }
                })
    except Exception as e:
        logger.error("WS error: %s", str(e), exc_info=True)
        ws_manager.unregister(websocket)
