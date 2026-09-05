# Relationship OS - Engineering Bug Post-Mortem & Resolutions Log

This document records the critical technical challenges, subtle concurrency bugs, and architectural edge cases encountered during the design and construction of Relationship OS, alongside their root causes and production resolutions.

---

### BUG-001: MissingGreenlet Lazy-Loading Exception on Message Sender

- **Severity:** High (Crash on search and history retrieval)
- **Component:** `apps/api/src/services/message_service.py` & `apps/api/src/routers/conversations.py`
- **Symptom:**
  ```
  sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called; can't call a synchronous function with an async engine
  ```
- **Root Cause:**
  In `conversations.py`, the response serialization accessed `m.sender.display_name`. Because `MessageService.get_history` and `MessageService.search_messages` queried `select(Message)` without eager loading the `sender` relationship, SQLAlchemy attempted to dynamically fetch the associated `User` model on demand. In asynchronous SQLAlchemy mode, synchronous attribute-level lazy loading is disallowed and raises `MissingGreenlet`.
- **Resolution:**
  Imported `selectinload` from `sqlalchemy.orm` and explicitly chained `.options(selectinload(Message.sender))` to the queries in both `get_history` and `search_messages`. This fetches sender metadata in an optimized, non-blocking sub-query.

---

### BUG-002: Concurrent Monotonic Sequence Number Gaps & Conflicts

- **Severity:** Critical (Data Integrity)
- **Component:** `MessageService.send_message` & Database unique constraints
- **Symptom:**
  Under high-frequency concurrent message sending from multiple clients, two concurrent coroutines could read the same `MAX(sequence_number)` before either committed, leading to duplicate sequence numbers or database integrity errors.
- **Root Cause:**
  Classic read-modify-write race condition during sequence number assignment.
- **Resolution:**
  Implemented a dual-layer concurrency protection strategy:
  1. **In-Process Per-Conversation Async Locking:** Maintained an in-memory dictionary `_conversation_locks: Dict[str, asyncio.Lock]`. Each message write in a room acquires the conversation's lock before computing `MAX(sequence_number) + 1` and inserting the record.
  2. **Database Unique Constraint & Fallback:** Backed by `UniqueConstraint("conversation_id", "sequence_number", name="uq_message_conversation_sequence")`. If a distributed conflict occurs, the service catches `IntegrityError`, rolls back, checks for idempotency by `client_message_id`, and safely resolves the state.

---

### BUG-003: Asynchronous Session Sharing Across Concurrent Coroutines in Tests

- **Severity:** High (Test suite flaky failures during load tests)
- **Component:** `tests/load/test_concurrency.py` & `tests/conftest.py`
- **Symptom:**
  ```
  sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread
  sqlalchemy.exc.InvalidRequestError: Cannot operate on a closed transaction inside a concurrent task
  ```
- **Root Cause:**
  The `db_session` test fixture yielded a single `AsyncSession` instance that was shared across multiple parallel requests launched via `asyncio.gather`. Concurrent database queries on a single session violate SQLAlchemy's session thread/coroutine safety rules.
- **Resolution:**
  Refactored `override_get_db` to instantiate a fresh `TestingSessionLocal()` for each HTTP request, operating on top of a shared in-memory `StaticPool` SQLite engine. This mirrors production where each request receives its own isolated database session.

---

### BUG-004: Starlette TestClient WebSocket Multi-Client Broadcast Deadlock

- **Severity:** Medium (Blocked WebSocket testing)
- **Component:** `tests/integration/test_websocket.py`
- **Symptom:**
  Tests attempting to open two concurrent WebSocket connections with `client.websocket_connect()` hung indefinitely when broadcasting messages between parties.
- **Root Cause:**
  Starlette's `TestClient` manages WebSocket connections synchronously on top of AnyIO worker threads. When connection A is waiting on `receive_json()`, the event loop in the worker thread blocks, preventing connection B's broadcast handler from dispatching to connection A.
- **Resolution:**
  Engineered a production-accurate `live_server` pytest fixture in `tests/conftest.py`. The fixture boots an actual Uvicorn server in a daemon thread bound to an ephemeral localhost port (`127.0.0.1:0`). Tests connect using real asynchronous `websockets.connect()` sockets, enabling genuine full-duplex, multi-client integration testing.

---

### BUG-005: Duplicate Security Headers in File Downloads

- **Severity:** Low (Browser warning / standards violation)
- **Component:** `apps/api/src/routers/attachments.py` & `RequestContextAndSecurityHeadersMiddleware`
- **Symptom:**
  HTTP responses returned `X-Content-Type-Options: nosniff, nosniff`.
- **Root Cause:**
  `RequestContextAndSecurityHeadersMiddleware` automatically adds `X-Content-Type-Options: nosniff` to every outgoing response. The file download endpoint manually added `headers={"X-Content-Type-Options": "nosniff"}`, causing Starlette to concatenate both into a comma-separated list.
- **Resolution:**
  Removed redundant manual header definitions from endpoint handlers, establishing the ASGI security middleware as the single source of truth for security headers.

---

### BUG-006: FastAPI 0.115 `_IncludedRouter` Route Inspection in Verification Script

- **Severity:** Low (Verification tooling failure)
- **Component:** `scripts/verify_integrity.py`
- **Symptom:**
  `AttributeError: '_IncludedRouter' object has no attribute 'path'` when reading `app.routes`.
- **Root Cause:**
  FastAPI version 0.115 introduced `_IncludedRouter` wrappers for routers registered via `app.include_router()`. Unlike individual `Route` objects, `_IncludedRouter` does not expose a `.path` attribute directly.
- **Resolution:**
  Updated `verify_api_routes()` to inspect `app.openapi().get("paths", {})`. This inspects all compiled endpoints and schema paths accurately regardless of internal routing wrappers.
