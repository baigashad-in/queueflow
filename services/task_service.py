import time
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.db_models import TaskRecord
from core.models import TaskStatus
from core.queue import push_task
from core.scheduler import schedule_task
from core.dlq import remove_from_dlq
from core.events import publish_task_event
from core.metrics import tasks_submitted_total, tasks_retried_total
from core.constants import CANCELLATION_MESSAGE
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

async def reset_task_for_retry(task: TaskRecord) -> None:
    """Reset a task's state for retry. Used by both  single retry and bulk DLQ retry."""
    task.status = TaskStatus.QUEUED
    task.error_message = None
    task.retry_count = 0
    task.started_at = None
    task.completed_at = None


async def cancel_task(task: TaskRecord) -> None:
    """Apply cancellation to a task."""
    task.status = TaskStatus.FAILED
    task.error_message = CANCELLATION_MESSAGE
    task.completed_at = datetime.now(timezone.utc)


async def submit_task_to_queue(task: TaskRecord, delay_seconds: int | None = None) -> None:
    """Route a task to immediate queue or scheduled queue."""
    if delay_seconds is not None:
        run_at = time.time() + delay_seconds
        await schedule_task(str(task.id), run_at)
        task.status = TaskStatus.PENDING
        logger.info(f"Task scheduled: {task.id} runs in {delay_seconds}s.")
    else:
        await push_task(str(task.id), task.priority)
        task.status = TaskStatus.QUEUED
        logger.info(f"Task queued: {task.id} [{task.task_name}] priority = {task.priority}.")
    
