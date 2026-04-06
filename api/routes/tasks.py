import time
import uuid
import logging

from typing import Optional
from datetime import datetime, timezone

from django import tasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from core.database import get_session 
from core.models import TaskStatus
from core.queue import push_task
from core.metrics import tasks_submitted_total
from core.scheduler import schedule_task
from core.events import publish_task_event
from core.db_models import Tenant, TaskRecord

from api.auth import get_current_tenant
from api.schemas import TaskSubmitRequest, TaskResponse, TaskListResponse

from fastapi import APIRouter, Depends, HTTPException, Query
from repositories.task_repo import get_by_id, get_by_tenant

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
    await publish_task_event(task) # Publish event after task is submitted and status is updated
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

    # Fetch tasks for the tenant with pagination
    tasks, total = await get_by_tenant(
        session, tenant.id,
        status=status.value if status else None,
        page=page, page_size=page_size,
    )

    return TaskListResponse(tasks=tasks, total=total, page=page, page_size=page_size)

@router.get("/{task_id}", response_model = TaskResponse)
async def get_task(
    task_id: str, 
    session: AsyncSession = Depends(get_session),
    tenant: Tenant = Depends(get_current_tenant),
    ):
    """Get details of a specific task by ID."""
    task = await get_by_id(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task