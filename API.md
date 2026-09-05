# Relationship OS - API & WebSocket Protocol Reference

Relationship OS exposes a versioned, RESTful JSON API (`/api/v1`) alongside a bi-directional real-time WebSocket hub (`/ws/chat/{conversation_id}`).

---

## 1. Authentication & Common Conventions

### 1.1 Headers
Except for unauthenticated endpoints (`/health`, `/api/v1/auth/login`, `/api/v1/auth/enroll`), all API requests must include a Bearer token:

```http
Authorization: Bearer <SESSION_OR_ACCESS_TOKEN>
Content-Type: application/json
```

All responses return a correlation identifier in the `X-Request-ID` header.

### 1.2 Error Response Format
Errors follow standard HTTP status codes and return a consistent JSON payload:

```json
{
  "error": "ForbiddenException",
  "detail": "User is not an authorized participant in this conversation",
  "request_id": "4b68e92c-0e78-438f-a720-333e69fa020d"
}
```

---

## 2. Authentication Endpoints

### `POST /api/v1/auth/login`
Authenticates a user via username and password.

- **Request Body:**
```json
{
  "username": "recipient",
  "password": "RecipientSecurePass123!",
  "device_name": "Chrome on macOS",
  "platform": "web"
}
```
- **Response (200 OK):**
```json
{
  "access_token": "eyJh...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "c1f7a220-410a-4228-8d4e-e19ce3cf497f",
    "username": "recipient",
    "display_name": "Recipient (Partner)",
    "role": "recipient"
  }
}
```

### `POST /api/v1/auth/enroll`
Redeems a one-time high-entropy enrollment token to establish an active session.

- **Request Body:**
```json
{
  "token": "wXVwk37pxPlb4-oJN8RazbDPuLhP6nJoWE_aeLVUugU",
  "device_name": "MacBook Pro Terminal",
  "platform": "darwin"
}
```
- **Response (200 OK):** Same structure as `/login`.

### `GET /api/v1/auth/me`
Fetches the profile and active session details of the currently authenticated user.

### `GET /api/v1/auth/sessions`
Lists all active sessions associated with the current user.

### `POST /api/v1/auth/logout`
Revokes the current session token immediately.

---

## 3. Conversations & Messaging Endpoints

### `GET /api/v1/conversations`
Lists conversations the authenticated user is authorized to participate in.

### `GET /api/v1/conversations/{conversation_id}/messages`
Retrieves cursor-paginated message history.

- **Query Parameters:**
  - `before_seq` (integer, optional): Return messages with `sequence_number < before_seq`.
  - `after_seq` (integer, optional): Return messages with `sequence_number > after_seq`.
  - `limit` (integer, default 50, max 100): Maximum number of messages.
- **Response (200 OK):**
```json
[
  {
    "id": "e2c040d7-7aa4-473d-8e61-a083d9198642",
    "conversation_id": "cc9b89ab-1b4d-4d26-a790-2b63f481ed69",
    "sender_id": "c1f7a220-410a-4228-8d4e-e19ce3cf497f",
    "sender_name": "Recipient",
    "message_type": "text",
    "body": "Good morning! Can you check the project update?",
    "sequence_number": 1,
    "client_message_id": "client-uuid-12345",
    "delivery_state": "delivered",
    "created_at": "2026-09-05T14:00:00Z",
    "edited_at": null,
    "deleted_at": null
  }
]
```

### `POST /api/v1/conversations/{conversation_id}/messages`
Sends a message idempotently with monotonic sequence allocation and outbox dispatch.

- **Request Body:**
```json
{
  "client_message_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": {
    "type": "text",
    "body": "Hello from Relationship OS Web Client!"
  }
}
```
- **Response (201 Created):** Returns the canonical `MessageResponse`.

### `POST /api/v1/conversations/{conversation_id}/read`
Updates read receipt cursor for the authenticated user.

- **Request Body:**
```json
{
  "last_read_sequence": 15
}
```

### `GET /api/v1/conversations/{conversation_id}/search`
Searches message history using full substring matching.

- **Query Parameters:** `q` (string, min 1 char), `limit` (integer, default 20).

---

## 4. Admin & Operational Endpoints

*(Requires `role: owner` or `role: admin`)*

- `GET /api/v1/admin/health` - Cluster health and resource utilization metrics.
- `GET /api/v1/admin/sessions` - View all active user sessions across all devices.
- `DELETE /api/v1/admin/sessions/{session_id}/revoke` - Immediately invalidate a specific session.
- `DELETE /api/v1/admin/devices/{device_name}/revoke` - Invalidate all sessions bound to a given device name.
- `GET /api/v1/admin/webhooks` - List registered outbound webhook endpoints.
- `POST /api/v1/admin/webhooks` - Register a new webhook endpoint (subject to SSRF validation).
- `DELETE /api/v1/admin/webhooks/{webhook_id}` - Delete a webhook configuration.
- `GET /api/v1/admin/deliveries/failed` - List dead-lettered message deliveries.
- `POST /api/v1/admin/deliveries/{delivery_id}/retry` - Manually requeue a failed delivery event.
- `GET /api/v1/admin/audit` - Inspect the tamper-evident system audit log.

---

## 5. Webhook Inbound Ingestion

### `POST /api/v1/webhooks/inbound`
Allows owner integrations (e.g. custom bot, cloud function) to post replies into the conversation.

- **Required Headers:**
  - `X-Relationship-Signature: v1=<hmac_sha256>`
  - `X-Relationship-Timestamp: <unix_seconds>`
- **Request Body:**
```json
{
  "conversation_id": "cc9b89ab-1b4d-4d26-a790-2b63f481ed69",
  "sender_name": "Owner (Discord)",
  "body": "Got your message, working on it now!",
  "client_message_id": "discord-msg-991823"
}
```

---

## 6. Real-Time WebSocket Protocol

### Connection URL:
```
ws://localhost:8000/ws/chat/{conversation_id}?token=<ACCESS_OR_SESSION_TOKEN>
```

### Protocol Frames:

#### 1. Keepalive Ping / Pong
- Client sends: `{"type": "ping"}`
- Server responds: `{"type": "pong", "timestamp": "2026-09-05T14:05:00Z"}`

#### 2. Sequence Replay / Resync
- Client sends on reconnect: `{"type": "sync", "after_sequence": 14}`
- Server responds: `{"type": "sync_result", "messages": [...]}`

#### 3. Typing Notification
- Client sends: `{"type": "typing", "conversation_id": "...", "is_typing": true}`
- Broadcasts to room: `{"type": "typing", "user_id": "...", "display_name": "...", "is_typing": true}`

#### 4. Live Message Send
- Client sends: `{"type": "send", "client_message_id": "...", "body": "..."}`
- Server processes via `MessageService.send_message` and broadcasts:
```json
{
  "type": "event",
  "event_id": "c71a3962-43bb-4d51-8408-ddad2eb9c9b1",
  "event_type": "message.created",
  "payload": {
    "id": "c71a3962-43bb-4d51-8408-ddad2eb9c9b1",
    "conversation_id": "cc9b89ab-1b4d-4d26-a790-2b63f481ed69",
    "sender_id": "...",
    "sender_name": "Recipient",
    "body": "Hello world",
    "sequence_number": 15,
    "delivery_state": "delivered",
    "created_at": "2026-09-05T14:06:00Z"
  }
}
```
