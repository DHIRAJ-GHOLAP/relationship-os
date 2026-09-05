# Relationship OS - Developer & Contributor Guide

Welcome to the Relationship OS developer guide. This document provides setup instructions, workflow standards, database migration guides, and testing conventions for engineers extending the platform.

---

## 1. Local Environment Setup

### 1.1 Requirements
- **Python 3.11+** (Python 3.13 tested and recommended)
- **Node.js 18+** and **npm 9+**
- **Git**

### 1.2 Initial Setup
```bash
# 1. Clone repository
git clone https://github.com/relationship-os/relationship-os.git
cd relationship-os

# 2. Setup Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install backend & integration dependencies
pip install -r packages/requirements.txt  # Or pip install fastapi uvicorn ...

# 4. Setup web frontend
cd apps/web
npm install
npm run build
cd ../..

# 5. Initialize & Seed database
PYTHONPATH=. python3 scripts/seed.py
```

---

## 2. Running Services Locally

### Option A: Integrated Development Server (FastAPI + Embedded SPA)
```bash
./scripts/dev/dev-start.sh
```
The server runs at `http://127.0.0.1:8000` with live backend auto-reload.

### Option B: Decoupled Full-Stack Development (Hot Reloading)
In Terminal 1 (Backend API):
```bash
PYTHONPATH=. .venv/bin/uvicorn apps.api.src.main:app --host 127.0.0.1 --port 8000 --reload
```

In Terminal 2 (Web Client with Vite HMR):
```bash
cd apps/web
npm run dev
```
Vite dev server runs at `http://localhost:5173` and proxies API/WebSocket calls to `http://localhost:8000`.

In Terminal 3 (Terminal Client):
```bash
PYTHONPATH=. .venv/bin/python3 apps/cli/src/cli.py --server http://127.0.0.1:8000
```

---

## 3. Database & Migrations Workflow

Relationship OS uses **SQLAlchemy 2.0 Async** declarative models mapped via Alembic migrations.

### Model Location:
All models reside in `apps/api/src/models/`. When altering entities:
1. Modify or add models in `apps/api/src/models/`.
2. Register the model in `apps/api/src/models/__init__.py`.
3. Generate a new migration revision:
   ```bash
   PYTHONPATH=. .venv/bin/alembic -c apps/api/alembic.ini revision --autogenerate -m "Add new field to message"
   ```
4. Inspect the generated migration file in `apps/api/alembic/versions/`.
5. Apply the migration:
   ```bash
   PYTHONPATH=. .venv/bin/alembic -c apps/api/alembic.ini upgrade head
   ```

---

## 4. Testing & Verification Standards

We maintain a strict **100% passing test requirement**. All pull requests must pass the complete test suite:

```bash
# Run entire automated test suite
./scripts/test/run-all-tests.sh

# Run specific test suites
PYTHONPATH=. .venv/bin/pytest tests/unit/ -v
PYTHONPATH=. .venv/bin/pytest tests/integration/ -v
PYTHONPATH=. .venv/bin/pytest tests/security/ -v
PYTHONPATH=. .venv/bin/pytest tests/load/ -v
PYTHONPATH=. .venv/bin/pytest tests/e2e/ -v

# Run system integrity verification
PYTHONPATH=. .venv/bin/python3 scripts/verify_integrity.py
```

### Test Design Guidelines:
- **Async Isolation:** Always use the `db_session` fixture. Ensure concurrent test coroutines instantiate separate sessions from `TestingSessionLocal` to prevent SQLite cross-coroutine cursor conflicts.
- **WebSocket Testing:** Always use the `live_server` fixture with real async `websockets.connect()` rather than synchronous TestClients to avoid thread deadlocks during multi-client broadcasts.
- **SSRF Safety:** Never disable the SSRF validator in production-facing router tests.

---

## 5. Coding Standards & Linting
- **Python:** PEP 8 compliance, explicit type annotations on all function signatures.
- **TypeScript:** Strict mode enabled in `tsconfig.json`.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`).
