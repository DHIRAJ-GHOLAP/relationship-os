"""Global pytest fixtures for unit, integration, and E2E testing."""

import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.src.core.database import Base, get_db
from apps.api.src.core.security import create_access_token
from apps.api.src.main import app
from apps.api.src.models.user import User
from apps.api.src.models.conversation import Conversation
from apps.api.src.models.participant import ConversationParticipant
from apps.api.src.models.session import Session
from packages.shared.src.constants import UserRole
from packages.shared.src.crypto import hash_password, hash_token, generate_secure_token


from sqlalchemy.pool import StaticPool

import apps.api.src.core.database
import apps.api.src.routers.websocket
import apps.api.src.services.outbox_worker

# Test in-memory SQLite database
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

apps.api.src.core.database.AsyncSessionLocal = TestingSessionLocal
apps.api.src.routers.websocket.AsyncSessionLocal = TestingSessionLocal
apps.api.src.services.outbox_worker.AsyncSessionLocal = TestingSessionLocal
# Disable automatic background outbox loop during tests to prevent race conditions with mock routers
apps.api.src.main.outbox_worker.start = lambda *args, **kwargs: None



@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh isolated in-memory database for each test function."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client wired to the isolated test database."""
    async def override_get_db():
        async with TestingSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def live_server(db_session: AsyncSession):
    """Run a live Uvicorn server on an ephemeral port for real-time WebSocket and network testing."""
    import socket
    import threading
    import uvicorn

    def get_free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    port = get_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to start
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)

    base_url = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}"

    yield {"base_url": base_url, "ws_url": ws_url, "port": port}

    server.should_exit = True
    thread.join(timeout=3)


@pytest_asyncio.fixture(scope="function")
async def test_users(db_session: AsyncSession):
    """Seed Owner, Recipient, and Admin test users."""
    owner = User(
        username="owner_user",
        display_name="Owner Alice",
        hashed_password=hash_password("OwnerSecurePass123!"),
        role=UserRole.OWNER,
        is_active=True,
    )
    recipient = User(
        username="recipient_user",
        display_name="Recipient Bob",
        hashed_password=hash_password("RecipientSecurePass123!"),
        role=UserRole.RECIPIENT,
        is_active=True,
    )
    admin = User(
        username="admin_user",
        display_name="Admin Charlie",
        hashed_password=hash_password("AdminSecurePass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )

    db_session.add_all([owner, recipient, admin])
    await db_session.commit()

    # Create canonical conversation between owner and recipient
    conv = Conversation(
        title="Private Room ♥",
        type="direct",
        status="active",
        metadata_json="{}",
    )
    db_session.add(conv)
    await db_session.commit()

    p1 = ConversationParticipant(conversation_id=conv.id, user_id=owner.id, last_read_sequence=0)
    p2 = ConversationParticipant(conversation_id=conv.id, user_id=recipient.id, last_read_sequence=0)
    db_session.add_all([p1, p2])
    await db_session.commit()

    return {
        "owner": owner,
        "recipient": recipient,
        "admin": admin,
        "conversation": conv,
    }


@pytest_asyncio.fixture(scope="function")
async def auth_headers(db_session: AsyncSession, test_users):
    """Helper returning auth bearer headers for owner, recipient, and admin."""
    from datetime import datetime, timedelta, timezone

    tokens = {}
    for role_name in ["owner", "recipient", "admin"]:
        user = test_users[role_name]
        raw_token = generate_secure_token(32)
        sess = Session(
            user_id=user.id,
            device_name=f"{role_name} Device",
            platform="linux",
            token_hash=hash_token(raw_token),
            is_revoked=False,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            last_seen_at=datetime.now(timezone.utc),
        )
        db_session.add(sess)
        await db_session.commit()

        jwt_token = create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
            session_id=sess.id,
            device_name=sess.device_name,
        )
        tokens[role_name] = {
            "Authorization": f"Bearer {jwt_token}",
            "token": jwt_token,
            "session_id": sess.id,
        }

    return tokens
