import logging
import time
import asyncio
import uuid

from core.queue import redis_client
from core.constants import HEARTBEAT_PREFIX

logger = logging.getLogger(__name__)


async def send_heartbeat(worker_id: str):
    """Send a single heartbeat update to Redis."""
    try:
        await redis_client.setex(f"{HEARTBEAT_PREFIX}{worker_id}", 30, str(time.time()))
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
    

async def heartbeat_loop(worker_id: str, interval: int = 10, shutdown_event = None):
    """Periodically update the worker's heartbeat in Redis.
    
    Args:
        worker_id: unique identifier for this worker instance.
        interval: secondes between heartbeats.
        shutdown_event: optional asyncio.Event for graceful stop. When set,
        the loop exits within 'interval' seconds. Default: None (loop
        runs forever - current production behavior).
        """
    while True:
        try:
            await send_heartbeat(worker_id)
        except Exception as e:
            logger.error(f"Failed to update heartbeat for worker {worker_id}: {e}")

        if shutdown_event is not None:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout = interval)
                if shutdown_event.is_set():
                    return
            except asyncio.TimeoutError:
                continue
        else:
            await asyncio.sleep(interval)

