import json
import logging

from core.queue import redis_client
from core.constants import EVENTS_CHANNEL

logger = logging.getLogger(__name__)

# CHANNEL = "queueflow:events"

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

        