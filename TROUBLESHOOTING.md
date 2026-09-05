# Relationship OS - Troubleshooting Guide

This guide details common error states, root causes, and diagnostic steps across the Relationship OS backend, web client, terminal client, and integration adapters.

---

## 1. WebSocket Connection Drops or Fails (Error 1006)

### Symptoms
The web or terminal client connects but disconnects after 60 seconds, or fails to establish a connection.

### Root Causes & Solutions
1. **Nginx Reverse Proxy Timeout:**
   - Standard Nginx closes idle HTTP/1.1 connections after `proxy_read_timeout 60s`.
   - **Fix:** Verify `nginx.conf` contains `proxy_read_timeout 86400s;` and `proxy_send_timeout 86400s;` for the `/ws/` location block, along with the WebSocket upgrade headers:
     ```nginx
     proxy_set_header Upgrade $http_upgrade;
     proxy_set_header Connection "Upgrade";
     ```
2. **Expired or Revoked Session Token:**
   - WebSocket handshakes require a valid `?token=<jwt>` query parameter.
   - If the token is expired or revoked via the admin dashboard, the server rejects the connection with HTTP `401 Unauthorized`.
   - **Fix:** Re-authenticate in the web client or re-enroll via CLI.

---

## 2. SSRF Protection Blocks Webhook Registration

### Symptoms
`POST /api/v1/admin/webhooks` returns:
```json
{
  "error": "ValidationException",
  "detail": "SSRF Protection: Hostname 'localhost' resolves to private IP '127.0.0.1'"
}
```

### Root Cause & Solutions
- By default, Relationship OS actively blocks destinations resolving to loopback (`127.0.0.1`), RFC1918 private IPs (`10.x`, `172.16.x`, `192.168.x`), and AWS/GCP instance metadata (`169.254.169.254`).
- **For Production:** Register public HTTPS webhook endpoints (e.g. `https://api.yourdomain.com/webhook`).
- **For Local Testing:** In unit/integration tests, pass `allow_localhost=True` to the SSRF validator or use an external tunneling service like ngrok/Cloudflare Tunnels.

---

## 3. SQLite Database Locked Contention

### Symptoms
API logs show `sqlite3.OperationalError: database is locked`.

### Root Causes & Solutions
1. **WAL Mode Disabled:**
   - Standard SQLite locks the entire database file during writes, blocking concurrent readers.
   - **Fix:** Relationship OS automatically sets `PRAGMA journal_mode=WAL;` and `PRAGMA busy_timeout=5000;`. Verify database connection strings use `sqlite+aiosqlite:////path/to/db`.
2. **High Concurrency Deployment:**
   - If servicing high concurrent throughput across multiple worker processes, switch to PostgreSQL by setting:
     ```ini
     DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/relationship_os
     ```

---

## 4. PowerShell Launcher ExecutionPolicy Restriction

### Symptoms
When executing `.\apps\launcher\Launch-RelationshipOS.ps1`, PowerShell outputs:
`File ... cannot be loaded because running scripts is disabled on this system.`

### Root Cause & Solution
Windows PowerShell defaults to `Restricted` script execution policy for standard users.
- **Fix (No admin required):**
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
  ```
  Or invoke the script with temporary bypass:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\apps\launcher\Launch-RelationshipOS.ps1
  ```

---

## 5. MissingGreenlet SQLAlchemy Error

### Symptoms
FastAPI outputs: `MissingGreenlet: greenlet_spawn has not been called; can't call a synchronous function with an async engine`.

### Root Cause & Solution
- Accessing an ORM relationship (e.g. `message.sender`) that was not eagerly loaded under asynchronous SQLAlchemy.
- **Fix:** Always include `selectinload(Model.relationship)` in the SQLAlchemy query:
  ```python
  from sqlalchemy.orm import selectinload
  stmt = select(Message).options(selectinload(Message.sender)).where(...)
  ```
