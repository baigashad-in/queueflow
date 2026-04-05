import logging
from core.queue import redis_client
from core.constants import DLQ_KEY

logger = logging.getLogger(__name__)

# DLQ_KEY = "queueflow:dlq"

async def push_to_dlq(task_id: str) -> None:
    """Push a failed task ID to the Dead Letter Queue (DLQ)."""
    await redis_client.lpush(DLQ_KEY, task_id)
    logger.warning(f"Task {task_id} pushed to DLQ.")

async def pop_from_dlq() -> str | None:
    """Pop a task ID from the Dead Letter Queue (DLQ)."""
    task_id = await redis_client.rpop(DLQ_KEY)
    if task_id:
        logger.warning(f"Task {task_id} popped from DLQ.")
    return task_id

async def get_dlq_contents() -> list[str]:
    """Get the list of task IDs currently in the Dead Letter Queue (DLQ)."""
    return await redis_client.lrange(DLQ_KEY, 0, -1)

async def get_dlq_depth() -> int:
    """Get the current depth of the Dead Letter Queue (DLQ)."""
    return await redis_client.llen(DLQ_KEY)

async def remove_from_dlq(task_id: str) -> None:
    """Remove a specific task ID from the Dead Letter Queue (DLQ)."""
    await redis_client.lrem(DLQ_KEY, 1, task_id)
    logger.warning(f"Task {task_id} removed from DLQ.")

async def purge_dlq() -> int:
    """Permanently remove a list of task IDs from the Dead Letter Queue (DLQ)."""
    depth = await get_dlq_depth()
    await redis_client.delete(DLQ_KEY)
    logger.warning(f"DLQ purged - {depth} tasks removed.")
    return depth