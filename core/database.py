from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import JSON, Column, Integer, String, DateTime, Text
from datetime import datetime, timezone
import uuid
from typing import AsyncGenerator

from core.config import settings

#create async engine
engine = create_async_engine(settings.database_url, 
                             echo=settings.app_env == "development", #log SQL in development only,
                            pool_size=10,   #connection pool settings
                            max_overflow=20,)

# Session factory
AsyncSessionLocal = async_sessionmaker(engine,
                                       class_ = AsyncSession,
                                       expire_on_commit=False,
                                       )

class Base(declarative_base):
    pass

class TaskRecord(Base):
    """Permanent record of a task execution, stored in the database."""
    __tablename__ = "task_records"

    id = Column(uuid.UUID(as_uuis = True), primary_key = True, default=uuid.uuid4)

    # What to run
    task_name = Column(String(255), nullable=False, index=True)
    payload = Column(JSON, nullable=False, default=dict)

    # Priority(higher number = more urgent)
    priority = Column(Integer, nullable=False, default=5)

    # Lifecycle
    status = Column(String(50), nullable = False, default = "pending", index = True)

    # Retry tracking
    max_retries = Column(Integer, nullable=False, default = 3)
    retry_count = Column(Integer, nullable=False, default = 0)

    # Results
    max_retries = Column(JSON, nullable = True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default = lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable = False, default= lambda: datetime.now(timezone.utc), onupdate = lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone= True), nullable=True)
    completed_at = Column(DateTime(timezone= True), nullable = True)

    def __repr__(self):
        return f"<Task {self.id} [{self.task_name}] status = {self.status}>"
    

async def init_db():
    """Create all tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI route injection."""
    async with AsyncSessionLocal() as session:
        yield session






