from core.queue import redis_client
import logging
import time
import asyncio
import uuid

logger = logging.getLogger(__name__)

HEARTBEAT_PREFIX = "queueflow:worker:"

worker_id = str(uuid.uuid4())[:8]  # Short unique ID for this worker instance

async def send_heartbeat(worker_id: str):
    """Send a single heartbeat update to Redis."""
    try:
        await redis_client.setex(f"{HEARTBEAT_PREFIX}{worker_id}", ex=30, value=str(time.time()))
    except Exception as e:
        logger.error(f"Failed to send heartbeat for worker {worker_id}: {e}")

async def get_active_workers() -> list[str]:
    """Get a list of active worker IDs based on recent heartbeats."""
    try:
        keys = await redis_client.keys(f"{HEARTBEAT_PREFIX}*")
        return [key.replace(HEARTBEAT_PREFIX, "") for key in keys]
    except Exception as e:
        logger.error(f"Failed to get active workers: {e}")
        return []
    

async def heartbeat_loop(worker_id: str, interval: int = 10):
    """Periodically update the worker's heartbeat in Redis."""
    while True:
        try:
            await send_heartbeat(worker_id)
        except Exception as e:
            logger.error(f"Failed to update heartbeat for worker {worker_id}: {e}")
        await asyncio.sleep(interval)

