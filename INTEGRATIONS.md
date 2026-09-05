# Relationship OS - Integrations Guide

Relationship OS features a pluggable, bi-directional integration architecture that enables the Owner to participate in the private conversation using existing channels such as **Discord** and **HMAC Webhooks**, with a roadmap for **Signal**.

---

## 1. Adapter Architecture Overview

All channel adapters implement the canonical `IntegrationAdapter` interface defined in `integrations/base.py`:

```python
class IntegrationAdapter(ABC):
    @abstractmethod
    async def send(self, event: CanonicalMessageEvent, config: Dict[str, Any]) -> bool:
        """Deliver an outbound canonical message event to the external provider."""
        pass

    @abstractmethod
    def sanitize(self, text: str) -> str:
        """Sanitize outbound content against protocol-specific injection or mass-pings."""
        pass
```

---

## 2. Discord Integration

### 2.1 Bot Setup on Discord Developer Portal
1. Navigate to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create a **New Application** named `Relationship OS Bridge`.
3. Under the **Bot** tab:
   - Click **Reset Token** and copy the Bot Token.
   - Under **Privileged Gateway Intents**, enable **Message Content Intent**.
4. Under **OAuth2 -> URL Generator**:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Read Message History`, `Attach Files`.
   - Copy the generated URL and authorize the bot into your private Discord server.
5. Create a dedicated private channel (e.g. `#sanctuary-chat`).
6. Right-click the channel, copy the **Channel ID**.

### 2.2 Server Configuration
Set the environment variables in `.env`:
```ini
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_CHANNEL_ID=123456789012345678
```

### 2.3 Mention Sanitization & Loop Prevention
- **Mention Sanitization:** Discord formatting like `@everyone`, `@here`, and `<@12345>` is automatically neutralized before sending:
  - `@everyone` $\rightarrow$ `[@everyone redacted]`
  - `@here` $\rightarrow$ `[@here redacted]`
  - `<@!123456789>` $\rightarrow$ `[mention redacted]`
- **Loop Prevention:** Inbound messages received from Discord carry metadata `origin: "discord"`. The outbox worker ignores events originating from Discord to prevent infinite echo loops.

---

## 3. Generic HMAC-SHA256 Webhook Integration

### 3.1 Outbound Webhooks (Relationship OS $\rightarrow$ External Server)
When the recipient sends a message, the outbox worker POSTs a signed JSON payload to configured webhook URLs.

#### Request Headers:
```http
POST /your-webhook-receiver HTTP/1.1
Host: your-server.com
Content-Type: application/json
X-Relationship-Timestamp: 1757065800
X-Relationship-Signature: v1=9b3a7...
X-Request-ID: d41d8cd9-8f00-4b68-8a8b-f4e7c7a72d7f
```

#### JSON Payload:
```json
{
  "event_id": "c71a3962-43bb-4d51-8408-ddad2eb9c9b1",
  "event_type": "message.created",
  "timestamp": "2026-09-05T14:06:00Z",
  "payload": {
    "id": "c71a3962-43bb-4d51-8408-ddad2eb9c9b1",
    "conversation_id": "cc9b89ab-1b4d-4d26-a790-2b63f481ed69",
    "sender_id": "user-uuid-1",
    "sender_name": "Recipient",
    "message_type": "text",
    "body": "Hello from Relationship OS!",
    "sequence_number": 42,
    "created_at": "2026-09-05T14:06:00Z"
  }
}
```

### 3.2 Sample Webhook Receiver (Python / FastAPI)

```python
import hmac
import hashlib
import time
from fastapi import FastAPI, Request, Header, HTTPException

app = FastAPI()
WEBHOOK_SECRET = "your_shared_webhook_secret"

@app.post("/webhook")
async def receive_webhook(
    request: Request,
    x_relationship_signature: str = Header(...),
    x_relationship_timestamp: int = Header(...),
):
    body = await request.body()
    
    # 1. Anti-Replay Check (5 minute window)
    if abs(int(time.time()) - x_relationship_timestamp) > 300:
        raise HTTPException(status_code=401, detail="Webhook timestamp expired")
        
    # 2. Re-compute HMAC
    signed_payload = f"t={x_relationship_timestamp}.".encode("utf-8") + body
    expected_sig = "v1=" + hmac.new(
        WEBHOOK_SECRET.encode("utf-8"), signed_payload, hashlib.sha256
    ).hexdigest()
    
    # 3. Constant-time comparison
    if not hmac.compare_digest(x_relationship_signature, expected_sig):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
    data = await request.json()
    print(f"Received message from {data['payload']['sender_name']}: {data['payload']['body']}")
    return {"status": "success"}
```

---

## 4. Inbound Webhook (External Server $\rightarrow$ Relationship OS)

To inject Owner replies back into the conversation, POST to `/api/v1/webhooks/inbound` with the same signature headers:

```bash
TIMESTAMP=$(date +%s)
BODY='{"conversation_id":"cc9b89ab-1b4d-4d26-a790-2b63f481ed69","sender_name":"Owner","body":"Reply from cloud","client_message_id":"ext-123"}'
SIG=$(echo -n "t=${TIMESTAMP}.${BODY}" | openssl dgst -sha256 -hmac "your_secret" | sed 's/^.* //')

curl -X POST http://localhost:8000/api/v1/webhooks/inbound \
  -H "Content-Type: application/json" \
  -H "X-Relationship-Timestamp: $TIMESTAMP" \
  -H "X-Relationship-Signature: v1=$SIG" \
  -d "$BODY"
```

---

## 5. Signal Integration Roadmap

An extensible stub exists in `integrations/signal/src/adapter.py`. Production deployment targets integration with an isolated `signal-cli-rest-api` container communicating over internal Docker bridge networks.
