# Relationship OS - Operations & Incident Runbook

This runbook covers operational procedures, health monitoring, incident mitigation, credential revocation, and dead-letter recovery for Relationship OS administrators.

---

## 1. System Health & Observability

### 1.1 Health Check Endpoints
- **Liveness Probe:** `GET /live` (Returns `200 OK` if the process is responsive).
- **Readiness Probe:** `GET /ready` (Verifies database connectivity and outbox worker loop).
- **Operational Metrics:** `GET /metrics` or `GET /api/v1/admin/health` (Reports active sessions, queue depths, and uptime).

```bash
# Verify cluster health via curl
curl -s http://localhost:8000/api/v1/admin/health \
  -H "Authorization: Bearer <ADMIN_OR_OWNER_TOKEN>"
```

Expected Response:
```json
{
  "status": "healthy",
  "app_version": "1.0.0",
  "database": "connected",
  "outbox_worker": "running",
  "pending_outbox_events": 0,
  "dead_letter_events": 0,
  "active_sessions": 2
}
```

---

## 2. Dead-Letter Queue & Outbox Recovery

When an external integration (e.g. Discord API outage or broken customer webhook) fails repeatedly, events transition to the `dead_letter` state after 5 retries.

### 2.1 Inspecting Failed Deliveries
```bash
curl -s http://localhost:8000/api/v1/admin/deliveries/failed \
  -H "Authorization: Bearer <ADMIN_OR_OWNER_TOKEN>"
```

### 2.2 Replaying a Failed Delivery
Once the destination endpoint is restored or DNS issues are resolved:
```bash
curl -X POST http://localhost:8000/api/v1/admin/deliveries/{delivery_id}/retry \
  -H "Authorization: Bearer <ADMIN_OR_OWNER_TOKEN>"
```
This resets the event's retry counter, recalculates exponential backoff, and re-queues it for immediate processing by the `OutboxWorker`.

---

## 3. Incident Response: Credential & Device Revocation

In the event of a lost phone, stolen laptop, or compromised recipient token:

### 3.1 Revoke Specific Session
```bash
curl -X DELETE http://localhost:8000/api/v1/admin/sessions/{session_id}/revoke \
  -H "Authorization: Bearer <ADMIN_OR_OWNER_TOKEN>"
```

### 3.2 Bulk Revoke All Sessions for a Device
```bash
curl -X DELETE http://localhost:8000/api/v1/admin/devices/{device_name}/revoke \
  -H "Authorization: Bearer <ADMIN_OR_OWNER_TOKEN>"
```
All active WebSocket connections and API calls associated with the target session are severed immediately with `401 Unauthorized`.

### 3.3 Audit Trail Investigation
Every security-relevant action (login, token redemption, revocation, failed signature, SSRF block) is appended to `audit_events`.
```bash
curl -s "http://localhost:8000/api/v1/admin/audit?limit=50" \
  -H "Authorization: Bearer <ADMIN_OR_OWNER_TOKEN>"
```

---

## 4. Maintenance & Database Optimization

### 4.1 SQLite Online WAL Checkpoint
If using SQLite, periodically truncate WAL files to maintain optimal read/write latency:
```bash
docker compose exec api python -c '
import sqlite3
con = sqlite3.connect("/app/data/relationship_os.db")
con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
con.close()
print("WAL checkpoint complete.")
'
```

### 4.2 Rotating Application Secret Key
To rotate `SECRET_KEY`:
1. Generate new key: `openssl rand -hex 32`
2. Update `SECRET_KEY` in `.env`.
3. Restart containers: `docker compose restart api`.
*(Note: Active JWT access tokens will be invalidated; users will automatically refresh or re-authenticate via their persistent session token).*
