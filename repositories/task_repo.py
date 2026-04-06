import uuid
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from core.db_models import TaskRecord

logger = logging.getLogger(__name__)


async def get_by_id(session: AsyncSession, task_id: str) -> TaskRecord | None:
    """Fetch a single task by UUID string."""
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        return None
    result = await session.execute(
        select(TaskRecord).where(TaskRecord.id == task_uuid)
    )
    return result.scalar_one_or_none()


async def get_by_tenant(
    session: AsyncSession,
    tenant_id,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[TaskRecord], int]:
    """Fetch paginated tasks for a tenant. Returns (tasks, total_count)."""
    query = select(TaskRecord).where(TaskRecord.tenant_id == tenant_id).order_by(TaskRecord.created_at.desc())
    count_query = select(func.count(TaskRecord.id)).where(TaskRecord.tenant_id == tenant_id)

    if status:
        query = query.where(TaskRecord.status == status)
        count_query = count_query.where(TaskRecord.status == status)

    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await session.execute(query)
    tasks = result.scalars().all()

    total_result = await session.execute(count_query)
    total = total_result.scalar()

    return tasks, total


async def get_by_ids(session: AsyncSession, task_ids: list[uuid.UUID]) -> list[TaskRecord]:
    """Fetch multiple tasks by UUID list."""
    result = await session.execute(
        select(TaskRecord).where(TaskRecord.id.in_(task_ids))
    )
    return result.scalars().all()