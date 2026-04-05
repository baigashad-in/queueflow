import logging

from core.queue import redis_client
from core.constants import LOCK_PREFIX

logger = logging.getLogger(__name__)

# LOCK_PREFIX = "queueflow:lock:"

async def acquire_lock(task_id: str, timeout: int =30) -> bool:
    """Try to acquire a lock for a task. Returns True if acquired."""
    key = f"{LOCK_PREFIX}{task_id}"
    result = await redis_client.set(key, "locked", nx = True, ex = timeout)
    if result:
        logger.info(f"Lock acquired for task {task_id}")
        return True
    else:
        logger.info(f"Failed to acquire lock for task {task_id} - skipping")
        return False
    
async def  release_lock(task_id: str) -> None:
    """Release the lock for a task."""
    key = f"{LOCK_PREFIX}{task_id}"
    await redis_client.delete(key)
    logger.info(f"Lock released for task {task_id}")


