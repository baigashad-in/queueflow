import os

# Browser CSWSH tests need the QueueFlow origin (http://127.0.0.1:18001)
# in the WS allowlist. This MUST be set before api.routes.ws is imported,
# because ALLOWED_WS_ORIGINS is read at module-import time. If we import api.main
# first, ALLOWED_WS_ORIGINS gets the defaults frozen in without our test origin.
os.environ["QUEUEFLOW_WS_ALLOWED_ORIGINS"] = ",".join([
    "http://localhost:5173",
    "http://20.240.221.65:8000",
    "http://20.240.221.65",
    "https://queueflow.swedencentral.cloudapp.azure.com",
    "http://127.0.0.1:18001",
])

import pytest

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as SyncSession

from core.database import Base, get_api_session
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
    """Create a test tenant and API key for authentication.
    
    Returns a dict with 'tenant', 'api_key' (the DB row, prefix-only),
    and 'cleartext_key' (the full key value, only available here because
    we generated it). Tests authenticating against the API should use
    cleartext_key in the X-API-Key header.
    """
    from core.key_utils import generate_api_key

    tenant = Tenant(name="TestTenant")
    test_session.add(tenant)
    await test_session.commit()
    await test_session.refresh(tenant)

    full_key, prefix, key_hash = generate_api_key()
    api_key = ApiKey(tenant_id = tenant.id, prefix = prefix, key_hash = key_hash)
    test_session.add(api_key)
    await test_session.commit()
    await test_session.refresh(api_key)

    return {"tenant": tenant, "api_key": api_key, "cleartext_key": full_key}


@pytest.fixture
async def client(test_session, test_tenant):
    """Create an AsyncClient for testing the FastAPI app, with the test database session and API key."""

    # Use ASGITransport to test the FastAPI app without running a server
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": test_tenant["cleartext_key"]},
    ) as client:
        yield client

    # Clear dependency overrides after the test finishes to avoid affecting other tests
    app.dependency_overrides.clear()

@pytest.fixture(autouse=True)
def fake_redis(monkeypatch, request):
    """
    Replace Redis with an in-memory fake — sync gate around the async impl.

    Browser tests use real Redis (via uvicorn-served app); non-browser tests
    get the fake. Sync gate so pytest-asyncio doesn't try to schedule us on
    a loop before the marker check.
    """
    if request.node.get_closest_marker("browser"):
        yield None
        return

    # For non-browser tests, defer to the async implementation
    yield request.getfixturevalue("_fake_redis_impl")

@pytest.fixture
async def _fake_redis_impl(monkeypatch):
    """The actual async fake-redis setup. Activated by the sync gate above."""    
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
    import core.ws_limits
 
    monkeypatch.setattr(core.queue, "redis_client", fake)
    monkeypatch.setattr(core.lock, "redis_client", fake)
    monkeypatch.setattr(core.dlq, "redis_client", fake)
    monkeypatch.setattr(core.scheduler, "redis_client", fake)
    monkeypatch.setattr(core.events, "redis_client", fake)
    monkeypatch.setattr(worker.heartbeat, "redis_client", fake)
    monkeypatch.setattr(core.rate_limiter, "redis_client", fake)
    monkeypatch.setattr(core.ws_limits, "redis_client", fake)
    
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


@pytest.fixture(autouse=True)
def _override_api_session(request):
    """Override get_api_session for every test.

    httpx.ASGITransport does not run FastAPI's lifespan events, so
    app.state.SessionLocal is never populated. We override
    get_api_session to yield from a per-call sessionmaker bound to
    the test engine.

    Per-call (not yielding a shared session) avoids 'another operation
    in progress' errors when multiple Depends(get_api_session) resolve
    within a single request.

    Skipped for tests marked @pytest.mark.browser — those go through real
    uvicorn (which runs the production lifespan with its own engine), so
    the dependency override mechanism is bypassed entirely.
    """
    if request.node.get_closest_marker("browser"):
        yield
        return
    
    # Resolve engine fixture only for non-browser tests
    engine = request.getfixturevalue("engine")

    from api.main import app
    from core.database import get_api_session, build_sessionmaker

    SessionLocal = build_sessionmaker(engine)

    async def override():
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_api_session] = override
    yield
    app.dependency_overrides.pop(get_api_session, None)

@pytest.fixture
def ws_test_client(monkeypatch, engine):
    """TestClient with real DB-backed WebSocket auth.

    TestClient runs the ASGI app in its own thread with its own event
    loop. The production lifespan runs in that loop and populates
    app.state.engine + app.state.SessionLocal there, bound to the
    TestClient loop and pointing at the same test database that the
    main test loop uses.

    Tests seed tenant/api_key rows via test_session_sync (a sync engine,
    independent of either async loop) and connect with a cookie matching
    the seeded api_key.

    APP_ENV=testing causes the lifespan to skip Base.metadata.create_all
    — the test engine fixture already created the schema.
    """
    monkeypatch.setenv("APP_ENV", "testing")
    from core.config import settings
    monkeypatch.setattr(settings, "app_env", "testing", raising=False)

    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope = "session")
def queueflow_server():
    """Run uvicorn on a real port so areal browser can talk to QueueFlow.
    
    The unit-test suite uses ASGITransport (in-process, not network-visible).
    Playwright drives a real browser and needs a network-addressable target,
    so we spin up uvicorn here for the test session. Bound to localhost only;
    not exposed outside the container.
    """
    import threading
    import time
    import socket
    import uvicorn
    from api.main import app

    config = uvicorn.Config(app, host = "127.0.0.1", port = 18001, log_level = "warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target = server.run, daemon = True)
    thread.start()

    # Poll until uvicorn accepts connections (max ~5s)
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", 18001), timeout = 0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("queueflow_server did not come up in time")
    
    yield "http://127.0.0.1:18001"
    server.should_exit = True
    thread.join(timeout=5)  # let uvicorn actually shut down before next session

@pytest.fixture(scope = "session")
def attacker_server(tmp_path_factory):
    """Serve an attacker HTML page from a different origin (different port).
    
    Used by CSWSH browser tests: the page contains JS that opens a WS to
    QueueFlow. Different port means different origin, which triggers the 
    cross-origin Origin header from Chromium.
    """

    import http.server
    import socketserver
    import threading
    import time
    import socket

    attacker_dir = tmp_path_factory.mktemp("attacker_origin")
    (attacker_dir / "evil.html").write_text(
        """
        <!doctype html>
        <html>
            <body>
                <script>
                    window.attackResult = new Promise((resolve) => {
                    const ws = new WebSocket("ws://127.0.0.1:18001/ws/tasks");
                    ws.onopen = () => resolve({outcome: "connected"});
                    ws.onclose = (e) => resolve({outcome: "closed", code: e.code, reason: e.reason});
                    ws.onerror = () => resolve({outcome: "error"});
                    setTimeout(() => resolve({outcome: "timeout"}), 5000);
                    });
                </script>
            </body>
        </html>
        """
    )

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(attacker_dir), **kwargs)
        def log_message(self, *args, **kwargs):
            pass  # silence access log noise

    # Subclass with allow_reuse address so TIME_WAIT sockets from prior
    # test runs don't block rebinding to 18002.
    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    
    httpd = ReusableTCPServer(("127.0.0.1", 18002), Handler)
    thread = threading.Thread(target = httpd.serve_forever, daemon = True)
    thread.start()

    for _ in range(20):
        try:
            with socket.create_connection(("127.0.0.1", 18002), timeout = 0.2):
                break
        except OSError:
            time.sleep(0.1)

    yield "http://127.0.0.1:18002"
    httpd.shutdown()
    httpd.server_close()  # actually release the socket


@pytest.fixture(scope="session")
def browser_test_db_engine():
    """Sync DB engine for browser tests.

    Browser tests are synchronous (Playwright sync API). They cannot
    depend on the async `engine` fixture without triggering pytest-asyncio
    loop conflicts. This fixture creates a sync engine directly and
    ensures the schema exists. Tables persist for the whole test session
    (no per-test teardown).
    """
    from core.config import settings
    sync_url = settings.database_url.replace("+asyncpg", "")
    sync_engine = create_engine(sync_url)
    # Schema is created by the queueflow_server fixture's lifespan, so
    # we don't run create_all here — just verify connection works.
    yield sync_engine
    sync_engine.dispose()


@pytest.fixture
def browser_test_session(browser_test_db_engine):
    """Sync session for seeding rows in browser tests."""
    SessionLocal = sessionmaker(bind=browser_test_db_engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
