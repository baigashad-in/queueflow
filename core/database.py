from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from typing import AsyncGenerator
from core.config import settings

#create async engine
engine = create_async_engine(settings.database_url, 
                             echo=settings.app_env == "development", # log SQL in development only,
                            pool_size=10,   #connection pool settings
                            max_overflow=20,)

# Session factory
AsyncSessionLocal = async_sessionmaker(engine,
                                       class_ = AsyncSession,
                                       expire_on_commit=False,
                                       )

class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI route injection."""
    async with AsyncSessionLocal() as session:
        yield session

