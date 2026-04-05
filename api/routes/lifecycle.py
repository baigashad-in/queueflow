from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid
import logging
from datetime import datetime, timezone

from core.database import get_session
from core.db_models import TaskRecord
from core.models import TaskStatus
from core.dlq import get_dlq_contents, get_dlq_depth, remove_from_dlq, purge_dlq, pop_from_dlq
from core.queue import push_task
from core.metrics import tasks_retried_total
from api.schemas import TaskResponse
from core.events import publish
from core.constants import CANCELLATION_MESSAGE


router = APIRouter(tags=["Lifecycle"])
logger = logging.getLogger(__name__)

async def get_task_or_404(task_id: str, session: AsyncSession) -> TaskRecord:
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code = 400, detail = "Invalid task ID format")
    
    result = await session.execute(
        select(TaskRecord).where(TaskRecord.id == task_uuid)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code = 404, detail = "Task not found")
    return task

@router.post("/tasks/{task_id}/cancel", response_model = TaskResponse, status_code=200)
async def cancel_task(task_id: str, session: AsyncSession = Depends(get_session)):
    """
    Cancel a task that is currently in the queue or being processed(pending).
    If the task is in the queue, it will be removed and marked as CANCELLED.
    If the task is currently being processed, it will be marked as CANCELLED, but the worker will need to check for this status and stop processing if possible.
    """
    
    task = await get_task_or_404(task_id, session)
    cancellable_statuses = [TaskStatus.PENDING, TaskStatus.QUEUED]
    if task.status not in cancellable_statuses:
        raise HTTPException(status_code = 409, detail = f"Task cannot be cancelled from status {task.status.value}")
    
    # if we get here, the task is either PENDING or QUEUED and can be cancelled
    task.status = TaskStatus.FAILED
    task.completed_at = datetime.now(timezone.utc)
    logger.info(f"Task {task.id} {CANCELLATION_MESSAGE}")
    task.error_message = CANCELLATION_MESSAGE
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

@router.post("/tasks/{task_id}/retry", response_model = TaskResponse)
async def retry_task(task_id: str, session: AsyncSession = Depends(get_session)):
    """
    Retry a task that is currently marked as FAILED and DEAD.
    The task will be re-queued and its status will be updated to PENDING.
    """
    task = await get_task_or_404(task_id, session)
    retryable_statuses = [TaskStatus.FAILED, TaskStatus.DEAD]
    if task.status not in retryable_statuses:
        raise HTTPException(status_code = 409, detail = f"Only tasks with FAILED or DEAD status can be retried. Current status: {task.status.value}")
    
  
    await remove_from_dlq(str(task.id)) # If the task isn't in the DLQ, LREM does nothing, it returns 0. No unnecessary Redis round-trip

    # if we get here, the task is either FAILED or DEAD and can be retried
    task.status = TaskStatus.QUEUED
    task.error_message = None
    task.retry_count = 0
    task.started_at = None
    task.completed_at = None
    await push_task(str(task.id), task.priority)
    tasks_retried_total.labels(
        task_name = task.task_name,
        priority = str(task.priority),
    ).inc() 

    logger.info(f"Task {task.id} is being retried by user.")
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

@router.get("/dlq", response_model = list[TaskResponse]  )
async def view_dlq( session: AsyncSession = Depends(get_session)):
    """View the contents of the Dead Letter Queue (DLQ). Returns a list of task IDs currently in the DLQ."""
    task_ids = await get_dlq_contents()
    if not task_ids:
        return []  # Return empty list if DLQ is empty
    
    # Convert string to UUIDS, Skipping any bad data
    uuid_list = []
    for task_id in task_ids:
        try:
            uuid_list.append(uuid.UUID(task_id))
        except ValueError:
            logger.warning(f"Invalid task ID in DLQ: {task_id}. Skipping.")
    
    if not uuid_list:
        return []  # Return empty list if no valid task IDs
    
    result = await session.execute(
        select(TaskRecord).where(TaskRecord.id.in_(uuid_list))
    )
    tasks = result.scalars().all()
    return tasks
    

@router.post("/dlq/retry-all")
async def retry_all_dlq_tasks(session: AsyncSession = Depends(get_session)):
    """Retry all tasks currently in the Dead Letter Queue (DLQ). Returns the number of tasks that were retried."""
    replayed = 0
    failed = 0

    while True:
        task_id = await pop_from_dlq()
        if task_id is None:
            break  # No more tasks in DLQ
        try:
            task_uuid = uuid.UUID(task_id)
        except ValueError:
            failed += 1
            continue  # Skip invalid task IDs

        result = await session.execute(
            select(TaskRecord).where(TaskRecord.id == task_uuid)
        )
        task = result.scalar_one_or_none()

        if not task:
            failed += 1
            continue  # Skip if task not found in database

        # Reset and re-enqueue (same as single retry)
        task.status = TaskStatus.QUEUED
        task.error_message = None
        task.retry_count = 0
        task.started_at = None
        task.completed_at = None
        await session.commit()
        await publish({
            "task_id": str(task.id),
            "task_name": task.task_name,
            "status": task.status.value if hasattr(task.status, "value") else task.status,
            "priority": task.priority,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await push_task(str(task.id), task.priority)

        tasks_retried_total.labels(
            task_name = task.task_name,
            priority = str(task.priority),
        ).inc()
        replayed += 1

    return {"replayed": replayed, "failed": failed}


@router.post("/dlq/purge", status_code = 200)
async def purge_dead_letter_queue():
    """Permanently remove all tasks from the Dead Letter Queue (DLQ). Returns the number of tasks that were removed."""
    removed_count = await purge_dlq()
    return {"message": f"DLQ purged. {removed_count} tasks removed."}




 