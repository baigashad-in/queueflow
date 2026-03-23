import logging
import asyncio

from core.config import settings
from core.queue import pop_task, get_queue_depths
from core.database import get_session, TaskRecord
from core.models import TaskStatus
from sqlalchemy import select
from datetime import datetime, timezone


logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

async def process_task(task: TaskRecord, session) -> None:
    """Execute a single task and update its status in Postgres."""

    logger.info(f"Processing task {task.id} [{task.task_type}] with payload: {task.payload}")

    # Mark as RUNNING
    task.status = TaskStatus.RUNNING
    task.started_at = datetime.now(timezone.utc)
    await session.commit()

    try:
        # Simulate work - Phase 4 will dispatch to real handlers
        logger.info(f"Executing {task.task_name} with payload: {task.payload}")
        await asyncio.sleep(1) # placeholder for real work
        
        # Mark as COMPLETED
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(timezone.utc)
        await session.commit()
        logger.info(f"Task {task.id} completed successfully.")
    
    except Exception as e:
        logger.error(f"Task {task.id} failed: {e}")

        task.retry_count += 1

        if task.retry_count <= task.max_retries:
            task.status = TaskStatus.PENDING
            logger.info(f"Retrying task {task.id} (attempt {task.retry_count}/{task.max_retries})")
        else:
            task.status = TaskStatus.DEAD
            task.error_message = str(e)
            logger.error(f"Task {task.id} exhausted retries and is now marked as DEAD.")
        await session.commit()


async def poll_loop():
    """Main worker loop - polls REdis and processes tasks."""
    logger.info("PyQueue Worker starting up...")
    logger.info(f"Worker concurrency: {settings.worker_concurrency}")
    while True:
        try:
            task_id = await pop_task()
            if not task_id:
                depths = await get_queue_depths()
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
                await process_task(task, session)
        except Exception as e:
            logger.error(f"Worker poll error: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(poll_loop())

    