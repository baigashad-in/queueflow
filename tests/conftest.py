import pytest
import asyncio
import uuid

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from core.database import Base, Tenant, ApiKey, get_session
from core.config import settings
from api.main import app


TEST_DATABASE_URL = settings.database_url.replace(
    f"/{settings.postgres_db}",
    f"/{settings.postgres_db}_test"
)

@pytest.fixture
async def client(test_session, test_tenant):
    """HTTP client with auth headers for testing."""
    # Override the session dependency
    async def override_get_session():
        yield test_session
    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app = app)
    async with AsyncClient(
        transport = transport, 
        base_url = "http://test",
        headers={"X-API-Key": test_tenant["api_key"].key}
        ) as client:
        yield client

    app.dependency_overrides.clear()

@pytest.fixture(scope = "session")
async def engine():
    """Create a test database engine."""
     # Create async engine
    engine = create_async_engine(TEST_DATABASE_URL)

    # Create tables before tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Provide the engine to session fixture to test
    yield engine 

    # Drop tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()

@pytest.fixture
async def test_session(engine):
    """Create a new database session for a test. And provides a fresh AsyncSession for each test."""
    async_session = async_sessionmaker(
        bind = engine, 
        expire_on_commit = False
    )
    async with async_session() as session:
        yield session

@pytest.fixture
async def test_tenant(test_session):
    """Creates a test tenant with an API key."""

    # Create a test tenant
    tenant = Tenant(
        name = "TestTenant"
    )
    test_session.add(tenant)
    await test_session.commit()
    await test_session.refresh(tenant)

    # Create an API key for the tenant
    api_key = ApiKey(
        tenant_id = tenant.id,
        key = "test-api-key"
    )
    test_session.add(api_key)
    await test_session.commit()
    await test_session.refresh(api_key)

    # Yield the tenant and API key for use in tests
    yield{"tenant": tenant, "api_key": api_key}

    # Cleanup: delete the tenant and API key after the test
    await test_session.delete(api_key)
    await test_session.delete(tenant)
    await test_session.commit()