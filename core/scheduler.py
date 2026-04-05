import time
import logging

from core.queue import redis_client
from core.constants import SCHEDULED_KEY

logger = logging.getLogger(__name__)
# REDIS_KEY = "queueflow:scheduled"

async def schedule_task(task_id: str, run_at_timestamp: float) -> None:
    """ Adds a task to the sorted set with the timestamp as the score. """
    logger.info(f"Scheduling task: {task_id} to run at {run_at_timestamp}")
    return await redis_client.zadd(SCHEDULED_KEY, {task_id: run_at_timestamp})


async def get_due_tasks() -> list[str]:
    """Returns all task IDs with score ≤ current time."""
    current_time = time.time()
    logger.info(f"Fetching due tasks at {current_time}")
    return await redis_client.zrangebyscore(SCHEDULED_KEY, "-inf", current_time)


async def remove_scheduled(task_id: str) -> None:
    """Removes a task from the scheduled set after it's been moved to the work queue. """
    logger.info(f"Removing scheduled task: {task_id}")
    return await redis_client.zrem(SCHEDULED_KEY, task_id)