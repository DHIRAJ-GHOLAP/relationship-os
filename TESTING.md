# Relationship OS - Automated Testing Strategy & Matrix

Relationship OS enforces rigorous automated testing across unit, integration, concurrency, security, and full end-to-end acceptance levels.

---

## 1. Testing Philosophy & Test Matrix

The platform is backed by **59 comprehensive tests** covering 100% of core domain workflows:

```
tests/
├── unit/                         # 17 Tests
│   ├── test_crypto.py            # Bcrypt, HMAC-SHA256, Anti-replay, Token entropy
│   ├── test_ssrf.py              # CIDR blacklist, DNS resolution, Loopback, Cloud metadata
│   ├── test_rate_limiter.py      # Sliding window algorithm, key isolation, burst thresholds
│   └── test_models.py            # Canonical message serialization, delivery state transitions
├── integration/                  # 34 Tests
│   ├── test_api_auth.py          # Password auth, RBAC, enrollment redemption, session revocation
│   ├── test_api_chat.py          # Monotonic sequencing, cursor pagination, read receipts, search
│   ├── test_websocket.py         # Async websocket client, live broadcast, sequence sync replay
│   ├── test_outbox_worker.py     # Background outbox draining, exponential backoff, dead-lettering
│   ├── test_adapters.py          # Discord mention sanitization, loop prevention, HMAC webhook
│   ├── test_admin_api.py         # Admin RBAC, health metrics, sessions, webhook CRUD, audit log
│   └── test_attachments_api.py   # Executable rejection, file size limits, traversal defense
├── security/                     # 5 Tests
│   └── test_security.py          # Security headers, IDOR prevention, SSRF matrix, entropy check
├── load/                         # 2 Tests
│   └── test_concurrency.py       # 20 concurrent monotonic sequence sends, 10 duplicate idempotency races
└── e2e/                          # 1 Test
    └── test_full_acceptance.py   # Complete 12-step multi-party cross-channel acceptance lifecycle
```

---

## 2. Test Infrastructure & Fixtures

### 2.1 Isolated In-Memory Database (`StaticPool`)
Tests execute against an in-memory SQLite database using SQLAlchemy's `StaticPool`. This ensures high-speed execution while maintaining ACID guarantees.

### 2.2 Coroutine Session Isolation
To prevent `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread` during concurrent load tests (`asyncio.gather`), the `override_get_db` fixture instantiates dedicated session scopes per coroutine request:
```python
async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session
```

### 2.3 Live WebSocket Testing Engine
Standard Starlette `TestClient.websocket_connect` operates synchronously over AnyIO threads, causing event loop deadlocks during concurrent multi-client broadcasts.

Relationship OS uses a custom `live_server` fixture in `tests/conftest.py` that boots a real, lightweight Uvicorn server on an ephemeral localhost port:
```python
@pytest.fixture(scope="session")
def live_server():
    # Spawns background thread with Uvicorn on localhost:ephemeral_port
```
Tests connect using genuine asynchronous `websockets.connect()` sockets, perfectly matching production behavior.

---

## 3. Running Tests

### 3.1 Run All Tests
```bash
./scripts/test/run-all-tests.sh
```

### 3.2 Run Specific Test Suites
```bash
# Unit tests
PYTHONPATH=. .venv/bin/pytest tests/unit/ -v

# Real-time WebSocket tests
PYTHONPATH=. .venv/bin/pytest tests/integration/test_websocket.py -v

# High-concurrency load tests
PYTHONPATH=. .venv/bin/pytest tests/load/ -v

# End-to-end acceptance lifecycle
PYTHONPATH=. .venv/bin/pytest tests/e2e/ -v
```

### 3.3 Code Coverage Report
```bash
PYTHONPATH=. .venv/bin/pytest tests/ \
  --cov=apps/api \
  --cov=packages/shared \
  --cov=integrations \
  --cov-report=term-missing
```
All core security and sequencing paths achieve near-100% branch coverage.
