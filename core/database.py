from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean, ForeignKey
from datetime import datetime, timezone
import uuid
from typing import AsyncGenerator, Sequence
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy import Sequence
import secrets



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

class Base(DeclarativeBase):
    pass

class Tenant(Base):
    """Represents a customer/organization in a multi-tenant setup."""
    __tablename__ = "tenants"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    is_active = Column(Boolean, default = True)
    created_at = Column(DateTime(timezone=True), nullable=False, default = lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Tenant {self.name} [{'active' if self.is_active else 'inactive'}]>"


class ApiKey(Base):
    """Represents an API key for authentication."""
    __tablename__ = "api_keys"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    key = Column(String(255), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(32))
    label = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default = lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<ApiKey {self.label} tenant = {self.tenant_id}>"
    
    
class TaskRecord(Base):
    """Permanent record of a task execution, stored in the database."""
    __tablename__ = "task_records"
    id = Column(PGUUID(as_uuid=True), primary_key = True, default=uuid.uuid4)

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
    max_results = Column(JSON, nullable = True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default = lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable = False, default= lambda: datetime.now(timezone.utc), onupdate = lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone= True), nullable=True)
    completed_at = Column(DateTime(timezone= True), nullable = True)

    # Auto-incrementing task number for easier human reference (not used for ordering)
    task_number_seq = Sequence("task_number_seq")
    task_number = Column(Integer, task_number_seq, server_default=task_number_seq.next_value(), unique=True, nullable=False)

    # Foreign key to Tenant for multi-tenancy support (optional)
    tenant_id = Column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)

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










