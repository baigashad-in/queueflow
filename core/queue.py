import redis.asyncio as aioredis
import json
import logging

from core.config import settings
from core.constants import QUEUE_HIGH, QUEUE_NORMAL, QUEUE_LOW

logger = logging.getLogger(__name__)

# Redis client (created once, reused)
redis_client = aioredis.from_url(
    settings.redis_url,
    encoding = "utf-8",
    decode_responses = True,
)

# Queue key constants
# QUEUE_HIGH = "queueflow:queue:high"      # priority >=8
# QUEUE_NORMAL = "queueflow:queue:medium"  # priority >=4 and <=7
# QUEUE_LOW = "queueflow:queue:low"        # priority <=3

def _get_queue_key(priority: int) -> str:
    """Map a numeric priority to the correct Redis list key."""
    if priority >= 8:
        return QUEUE_HIGH
    elif priority >= 4:
        return QUEUE_NORMAL
    else:
        return QUEUE_LOW
    

async def push_task(task_id: str, priority:int) -> None:
    """Push a task ID onto the appropriate priority queue."""
    queue_key = _get_queue_key(priority)
    await redis_client.lpush(queue_key, task_id)
    logger.info(f"Pushed task {task_id} to {queue_key} (priority {priority})")


async def pop_task() -> str | None:
    """ 
    Pop the next task ID from the highest-priority non-empty queue.
    Returns None if all queues are empty.
    """
    for queue_key in [QUEUE_HIGH, QUEUE_NORMAL, QUEUE_LOW]:
        task_id = await redis_client.rpop(queue_key)
        if task_id:
            logger.info(f"Task{task_id} popped from {queue_key}")
            return task_id
    return None

async def get_queue_depths() -> dict[str, int]:
    """Return the current depth of each queue. Useful for monitoring."""
    return{
        "high": await redis_client.llen(QUEUE_HIGH),
        "medium": await redis_client.llen(QUEUE_NORMAL),
        "low": await redis_client.llen(QUEUE_LOW),
        }