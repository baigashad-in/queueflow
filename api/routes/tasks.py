from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import logging
from typing import Optional



from core.database import get_session, TaskRecord
from core.models import TaskStatus
from api.schemas import TaskSubmitRequest, TaskResponse, TaskListResponse

router = APIRouter(prefix = "/tasks", tags = ["Tasks"])
logger = logging.getlogger(__name__)

@router.post("/", response_model = TaskResponse, status_code = 201)
async def submit_task(
    request: TaskSubmitRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Submit a new task to the queue.
    The task is saved tot he database with PENDING status.

    In Phase 3, this will also push the task into the Redis queue.
    """

    task = TaskRecord(
        task_name = request.task_name,
        payload = request.payload,
        priority = request.priority.value,
        max_retries = request.max_retries,
        status = TaskStatus.PENDING,
    )

    session.add(task)
    await session.commit()
    await session.refresh(task)
    logger.info(f"Task submitted: {task.id} [{task.task_name}] priority={task.priority}")

    return task

@router.get("/{task_id}", response_model = TaskResponse)
async def list_tasks(
    status: Optional[TaskStatus] = Query(None, description="Filter tasks by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """List all tasks with optional status filter and pagination."""

    # Base query
    query = select(TaskRecord).order_by(TaskRecord.created_at.desc())
    count_query = select(func.count(TaskRecord.id))

    # Apply filter
    if status:
        query = query.where(TaskRecord.status == status.value)
        count_query = count_query.where(TaskRecord.status == status.value)

    # Pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    # Execute queries
    result = await session.execute(query)
    tasks = result.scalars().all()

    total_result = await session.execute(count_query)
    total = total_result.scalar()

    return TaskListResponse(
        tasks=tasks,
        total=total,
        page=page,
        page_size=page_size,
    )