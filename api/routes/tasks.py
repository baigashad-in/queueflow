from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import logging
from typing import Optional
import uuid

from core.database import get_session, TaskRecord
from core.models import TaskStatus
from api.schemas import TaskSubmitRequest, TaskResponse, TaskListResponse
from core.queue import push_task
from core.metrics import tasks_submitted_total
import time
from core.scheduler import schedule_task
from core.events import publish
from core.database import Tenant
from api.auth import get_current_tenant


router = APIRouter(prefix = "/tasks", tags = ["Tasks"])
logger = logging.getLogger(__name__)

@router.post("/", response_model = TaskResponse, status_code = 201)
async def submit_task(
    request: TaskSubmitRequest,
    tenant: Tenant = Depends(get_current_tenant),
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
        tenant_id = tenant.id,
    )

    session.add(task)
    await session.commit()
    await session.refresh(task)

    # Record submission metric
    tasks_submitted_total.labels(
        task_name = task.task_name,
        priority = str(task.priority),
    ).inc()

    if request.delay_seconds is not None:
        run_at = time.time() + request.delay_seconds
        await schedule_task(str(task.id), run_at)
        logger.info(f"Task scheduled with delay: {task.id} to run at {request.delay_seconds} seconds from now")
        task.status = TaskStatus.PENDING
    else:
        # Push into Redis priority queue
        # Update status to QUEUED after pushing to Redis
        await push_task(str(task.id), task.priority)
        task.status = TaskStatus.QUEUED
        logger.info(f"Task queued: {task.id} [{task.task_name}] priority={task.priority}")

    await session.commit()

    await publish({
    "task_id": str(task.id),
    "task_name": task.task_name,
    "status": task.status.value if hasattr(task.status, "value") else task.status,
    "priority": task.priority,
    "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    await session.refresh(task)
    return task

@router.get("/", response_model = TaskListResponse)
async def list_tasks(
    status: Optional[TaskStatus] = Query(None, description="Filter tasks by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    tenant: Tenant = Depends(get_current_tenant),
):
    """List all tasks with optional status filter and pagination."""

    # Base query
    query = select(TaskRecord).where(TaskRecord.tenant_id == tenant.id).order_by(TaskRecord.created_at.desc())
    count_query = select(func.count(TaskRecord.id)).where(TaskRecord.tenant_id == tenant.id)

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

@router.get("/{task_id}", response_model = TaskResponse)
async def get_task(
    task_id: str, 
    session: AsyncSession = Depends(get_session),
    tenant: Tenant = Depends(get_current_tenant),
    ):
    """Get details of a specific task by ID."""
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")
    result = await session.execute(
        select(TaskRecord).where(TaskRecord.id == task_uuid)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.tenant_id != tenant.id:
            raise HTTPException(status_code = 404, detail = "Task not found")
    
    return task