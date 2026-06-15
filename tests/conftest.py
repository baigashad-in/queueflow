import pytest

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as SyncSession

from core.database import Base, get_session
from core.db_models import Tenant, ApiKey
from core.config import settings
from api.main import app
import fakeredis.aioredis

TEST_DATABASE_URL = settings.database_url

@pytest.fixture(scope="function")
async def engine():
    """Create a new database engine for each test, and drop all tables after the test finishes."""
    test_engine = create_async_engine(TEST_DATABASE_URL)
    # Create all tables before the test runs
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    # Drop all tables after the test finishes
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest.fixture
async def test_session(engine):
    """Create a new database session for each test."""
    async_session = async_sessionmaker(bind=engine, expire_on_commit=False)
    # Provide a session to the test, and ensure it's closed after the test finishes
    async with async_session() as session:
        yield session


@pytest.fixture
async def test_tenant(test_session):
    """Create a test tenant and API key for authentication."""
    tenant = Tenant(name="TestTenant")
    test_session.add(tenant)
    await test_session.commit()
    await test_session.refresh(tenant)

    # Create an API key for the tenant
    api_key = ApiKey(tenant_id=tenant.id, key="test-api-key-123")
    test_session.add(api_key)
    await test_session.commit()
    await test_session.refresh(api_key)

    return {"tenant": tenant, "api_key": api_key}


@pytest.fixture
async def client(test_session, test_tenant):
    """Create an AsyncClient for testing the FastAPI app, with the test database session and API key."""
    async def override_get_session():
        yield test_session

    # Override the get_session dependency to use the test session
    app.dependency_overrides[get_session] = override_get_session

    # Use ASGITransport to test the FastAPI app without running a server
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": test_tenant["api_key"].key},
    ) as client:
        yield client

    # Clear dependency overrides after the test finishes to avoid affecting other tests
    app.dependency_overrides.clear()

@pytest.fixture
async def fake_redis(monkeypatch):
    """
    Replace the real Redis client with an in-memory fake for the duration of one test.
 
    This monkeypatches `core.queue.redis_client` so that everything that imports
    redis_client from there (core.lock, core.dlq, core.scheduler, core.events,
    worker.heartbeat) transparently uses the fake.
 
    Each test gets a fresh fake — no state leaks between tests.
    """
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
 
    # Patch every module that imports redis_client.
    # We have to patch each binding because Python imports copy references.
    import core.queue
    import core.lock
    import core.dlq
    import core.scheduler
    import core.events
    import worker.heartbeat
    import core.rate_limiter
 
    monkeypatch.setattr(core.queue, "redis_client", fake)
    monkeypatch.setattr(core.lock, "redis_client", fake)
    monkeypatch.setattr(core.dlq, "redis_client", fake)
    monkeypatch.setattr(core.scheduler, "redis_client", fake)
    monkeypatch.setattr(core.events, "redis_client", fake)
    monkeypatch.setattr(worker.heartbeat, "redis_client", fake)
    monkeypatch.setattr(core.rate_limiter, "redis_client", fake)
 
    yield fake
 
    await fake.flushall()
    await fake.aclose()


@pytest.fixture
def test_session_sync(engine):
    """Synchronous DB session for use with starlette's TestClient.

    TestClient runs in a separate thread with its own event loop, so async
    sessions from the same engine can't be shared across the boundary.
    This fixture provides a sync session bound to the test database, useful
    for WebSocket tests that need to seed data before connecting.
    """
    # Derive a sync URL from the async one (replace +asyncpg with +psycopg2 or plain)
    from core.config import settings
    sync_url = settings.database_url.replace("+asyncpg", "")
    sync_engine = create_engine(sync_url)
    SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)
    session = SyncSessionLocal()
    try:
        yield session
    finally:
        session.close()
        sync_engine.dispose()


@pytest.fixture
def ws_test_client(monkeypatch):
    """TestClient that bypasses the WebSocket route's DB auth lookup entirely.

    Instead of patching get_session (which doesn't work because the async
    engine's connection pool is tied to the main test loop, while
    TestClient runs in its own thread/loop), we patch the
    `get_tenant_from_cookie` helper directly. Tests register a cookie→tenant
    mapping via the `register_session` method on the returned client.
    """
    monkeypatch.setenv("APP_ENV", "testing")
    from core.config import settings
    monkeypatch.setattr(settings, "app_env", "testing", raising=False)

    # In-memory cookie→tenant mapping populated by tests
    cookie_tenants = {}

    # Build a fake tenant class to mimic what the real route expects
    class FakeTenant:
        def __init__(self, tenant_id, is_active=True):
            self.id = tenant_id
            self.is_active = is_active

    async def fake_get_tenant_from_cookie(websocket):
        cookie = websocket.cookies.get("qf_session")
        if not cookie or cookie not in cookie_tenants:
            return None
        entry = cookie_tenants[cookie]
        if not entry["is_active"]:
            return None
        return FakeTenant(entry["tenant_id"], is_active=True)

    import api.routes.ws as ws_module
    monkeypatch.setattr(ws_module, "get_tenant_from_cookie", fake_get_tenant_from_cookie)

    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as client:
        # Attach helpers so tests can register sessions
        client.register_session = lambda cookie, tenant_id, is_active=True: (
            cookie_tenants.update({cookie: {"tenant_id": tenant_id, "is_active": is_active}})
        )
        yield client