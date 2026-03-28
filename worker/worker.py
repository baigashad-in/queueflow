import logging
import asyncio
import time

from core.config import settings
from core.queue import pop_task, get_queue_depths
from core.database import get_session, TaskRecord
from core.models import TaskStatus
from worker.handlers import dispatch
from core.metrics import (
    tasks_completed_total,
    tasks_failed_total,
    tasks_dead_total,
    task_processing_seconds,
    queue_depth,
    dlq_depth,
)
from sqlalchemy import select
from datetime import datetime, timezone
from prometheus_client import start_http_server
from core.dlq import push_to_dlq, get_dlq_depth

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

async def process_task(task: TaskRecord, session) -> None:
    """Execute a single task and update its status in Postgres."""

    logger.info(f"Processing task {task.id} [{task.task_name}] with payload: {task.payload}")

    # Mark as RUNNING
    task.status = TaskStatus.RUNNING
    task.started_at = datetime.now(timezone.utc)
    await session.commit()

    start_time = time.monotonic()

    try:
        # Dispatch to real handler
        result = await dispatch(task.task_name, task.payload)

        duration = time.monotonic() - start_time

        # Record metrics
        tasks_completed_total.labels(
            task_name = task.task_name,
            priority = task.priority,
        ).inc()
        task_processing_seconds.labels(
            task_name = task.task_name,
            priority = task.priority,
        ).observe(duration)
        
        # Store result and mark as COMPLETED
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(timezone.utc)
        task.max_results = result
        await session.commit()
        logger.info(f"Task {task.id} completed in {duration: .2f}s. Result: {result}")
    
    except Exception as e:
        duration = time.monotonic() - start_time
        logger.error(f"Task {task.id} failed: {e}")

        task.retry_count += 1

        if task.retry_count <= task.max_retries:
            task.status = TaskStatus.PENDING
            tasks_failed_total.labels(
                task_name = task.task_name,
                priority = task.priority,
            ).inc()
            logger.info(f"Retrying task {task.id} (attempt {task.retry_count}/{task.max_retries})")
        else:
            task.status = TaskStatus.DEAD
            task.error_message = str(e)
            tasks_dead_total.labels(
                task_name = task.task_name,
                priority = task.priority,
            ).inc()
            await push_to_dlq(str(task.id))
            logger.error(f"Task {task.id} exhausted retries and is now marked as DEAD.")
        await session.commit()


async def poll_loop():
    """Main worker loop - polls REdis and processes tasks."""
    logger.info("PyQueue Worker starting up...")
    logger.info(f"Worker concurrency: {settings.worker_concurrency}")

    # Start metrics server on the port 8001
    start_http_server(8001)
    logger.info("Worker metrics server started on port 8001")

    while True:
        try:
            task_id = await pop_task()

            if not task_id:
                # Update queue depth gauges
                depths = await get_queue_depths()
                queue_depth.labels(queue = "high").set(depths["high"])
                queue_depth.labels(queue = "medium").set(depths["medium"])
                queue_depth.labels(queue = "low").set(depths["low"])
                current_dlq_depth = await get_dlq_depth()
                dlq_depth.set(current_dlq_depth)
                logger.info(f"No tasks found. Queue depths: {depths}")
                await asyncio.sleep(5)
                continue

            #Fetch full task from Postgres
            async for session in get_session():
                result = await session.execute(
                    select(TaskRecord).where(TaskRecord.id == task_id)
                )
                task = result.scalar_one_or_none()

                if not task:
                    logger.warning(f"Task {task_id} not found in Postgres - skipping.")
                    continue

                if task.status == TaskStatus.FAILED and task.error_message == "Cancelled by user":
                    logger.info(f"Task {task_id} was cancelled by user - skipping.")
                    continue

                await process_task(task, session)

        except Exception as e:
            logger.error(f"Worker poll error: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(poll_loop())

    