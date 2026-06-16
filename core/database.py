from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import DeclarativeBase

from typing import AsyncGenerator
from core.config import settings


def build_engine() -> AsyncEngine:
    """Create a fresh async engine.
    
    Each call returns a NEW engine. Callers are responsible for disposing
    it on shutdown. Production callers:
    - api/main.py lifespan creates one and attaches it to app.state.
    - worker/worker.py module-level code creates one for the worker process
    """
    #create async engine
    return create_async_engine(settings.database_url, 
                             echo=settings.app_env == "development", # log SQL in development only,
                            pool_size=10,   #connection pool settings
                            max_overflow=20,)

def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the given engine."""
    # Session factory
    return async_sessionmaker(engine,
                              class_ = AsyncSession,
                              expire_on_commit=False,
                              )

class Base(DeclarativeBase):
    pass

engine = build_engine()
AsyncSessionLocal = build_sessionmaker(engine)

async def init_db():
    """Create all tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI route injection."""
    async with AsyncSessionLocal() as session:
        yield session

