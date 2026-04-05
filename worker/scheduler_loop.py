import asyncio
import logging

from core.scheduler import get_due_tasks, remove_scheduled
from core.queue import push_task
from core.database import get_session
from core.db_models import TaskRecord
from core.models import TaskStatus
from sqlalchemy import select


async def scheduler_loop():
    """ Continuously checks for due tasks and moves them to the work queue. """
    logger = logging.getLogger("scheduler_loop")
    logger.info("Scheduler loop started.")
    while True:
        try:
            due_task_ids = await get_due_tasks()
            if due_task_ids:
                logger.info(f"Found {len(due_task_ids)} due tasks: {due_task_ids}")
                for task_id in due_task_ids:
                    await remove_scheduled(task_id)
                    logger.info(f"Moved scheduled task to work queue: {task_id}")
                    
                    # Update task status in the database
                    async for session in get_session():
                        result = await session.execute(select(TaskRecord).where(TaskRecord.id == task_id))
                        task_record = result.scalar_one_or_none()
                        if task_record:
                            task_record.status = TaskStatus.QUEUED
                            await session.commit()
                            
                            # Move task to work queue
                            await push_task(task_id, task_record.priority)  # Use task's previous priority for scheduled tasks
                            logger.info(f"Scheduled task {task_id} moved to work queue with priority {task_record.priority}.")
                        else:
                            logger.warning(f"Task {task_id} not found in Postgres - skipping.")
            else:
                logger.info("No due tasks found.")
                await asyncio.sleep(5)
                continue

        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}")
        
        await asyncio.sleep(5)  # Sleep for a short interval before checking again
