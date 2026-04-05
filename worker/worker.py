import logging
import asyncio
import time
import signal
import uuid
import random

from core.config import settings
from core.queue import pop_task, get_queue_depths
from core.database import get_session, TaskRecord
from core.models import TaskStatus
from core.events import publish
from core.dlq import push_to_dlq, get_dlq_depth
from core.scheduler import schedule_task
from core.lock import acquire_lock, release_lock
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
from worker.scheduler_loop import scheduler_loop
from worker.heartbeat import heartbeat_loop
from worker.handlers import dispatch



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

    await publish({
        "task_id": str(task.id),
        "task_name": task.task_name,
        "status": task.status.value if hasattr(task.status, "value") else task.status,
        "priority": task.priority,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

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
        await publish({
            "task_id": str(task.id),
            "task_name": task.task_name,
            "status": task.status.value if hasattr(task.status, "value") else task.status,
            "priority": task.priority,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Task {task.id} completed in {duration: .2f}s. Result: {result}")
    
    except Exception as e:
        duration = time.monotonic() - start_time
        logger.error(f"Task {task.id} failed: {e}")

        task.retry_count += 1

        if task.retry_count <= task.max_retries:
            delay = (2 ** task.retry_count) + random.uniform(0, 1)  # Exponential backoff with jitter
            run_at = time.time() + delay
            await schedule_task(str(task.id), run_at)
            task.status = TaskStatus.RETRYING
            tasks_failed_total.labels(
                task_name = task.task_name,
                priority = task.priority,
            ).inc()
            logger.info(f"Retrying task {task.id} in {delay:.1f}s (attempt {task.retry_count}/{task.max_retries})")
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
        await publish({
            "task_id": str(task.id),
            "task_name": task.task_name,
            "status": task.status.value if hasattr(task.status, "value") else task.status,
            "priority": task.priority,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


async def process_with_limit(semaphore, task_id):
    """Process a task with concurrency limit and distributed locking to prevent multiple workers from processing the same task."""
    async with semaphore:
        if not await acquire_lock(task_id):
            return # Another worker is processing this task - skip it
        
        try:
            # If the task is not processed by another worker, we fetch it from the database and process it as usual. We also check if the task was cancelled by user while we were waiting for the lock - if so, we skip processing.
            async for session in get_session():
                result = await session.execute(
                    select(TaskRecord).where(TaskRecord.id == task_id)
                )
                task = result.scalar_one_or_none()
                if not task:
                    logger.warning(f"Task{task_id} not found - skipping")
                    return
                if task.status == TaskStatus.FAILED and task.error_message == "Cancelled by user":
                    logger.info(f"Task {task_id} was cancelled by user - skipping.")
                    return
                # await — blocks here until process_task finishes
                await process_task(task, session) 
        finally:
            await release_lock(task_id)
        

async def poll_loop():
    """Main worker loop - polls REdis and processes tasks."""
    logger.info("PyQueue Worker starting up...")
    logger.info(f"Worker concurrency: {settings.worker_concurrency}")

    semaphore = asyncio.Semaphore(settings.worker_concurrency)

    # Start metrics server on the port 8001
    start_http_server(8001)
    logger.info("Worker metrics server started on port 8001")

    shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)
    loop.add_signal_handler(signal.SIGINT, shutdown_event.set)

    active_tasks = set()


    while not shutdown_event.is_set():
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
            else:
                # create_task — starts it in the background and immediately continues. Runs right away, doesn't wait for the task to finish
                task_handle = asyncio.create_task(process_with_limit(semaphore, task_id))
                active_tasks.add(task_handle)
                task_handle.add_done_callback(active_tasks.discard)

        except Exception as e:
            logger.error(f"Worker poll error: {e}")
            await asyncio.sleep(5)

    logger.info(f"Shutting down - waiting for {len(active_tasks)} tasks to finish...")
    if active_tasks:
        await asyncio.gather(*active_tasks)
    logger.info("All tasks completed. Worker shutdown cleanly.")
    


if __name__ == "__main__":
    async def main():
        worker_id = str(uuid.uuid4())[:8]
        logger.info(f"Worker {worker_id} starting...")
        """Run the poll loop, scheduler loop and heatbeat loop concurrently."""
        await asyncio.gather(
            poll_loop(), 
            scheduler_loop(),
            heartbeat_loop(worker_id),
            )
    asyncio.run(main())

    