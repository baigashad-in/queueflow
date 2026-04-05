import pytest

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from core.database import Base, get_session
from core.db_models import Tenant, ApiKey
from core.config import settings
from api.main import app

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