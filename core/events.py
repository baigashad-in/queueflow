import json
import logging

from core.queue import redis_client
from core.constants import EVENTS_CHANNEL
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Redis Pub/Sub implementation (for multi-worker setups)
async def publish(event: dict) -> None:
    """Publish an event to Redis Pub/Sub."""
    await redis_client.publish(EVENTS_CHANNEL, json.dumps(event))

async def subscribe_to_events():
    """Async generator that yields events from Redis Pub/Sub."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(EVENTS_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(EVENTS_CHANNEL)


async def publish_task_event(task) -> None:
    """Publish a task status change event."""
    await publish({
        "task_id": str(task.id),
        "task_name": task.task_name,
        "status": task.status.value if hasattr(task.status, "value") else task.status,
        "priority": task.priority,
        "tenant_id": str(task.tenant_id) if task.tenant_id else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
        