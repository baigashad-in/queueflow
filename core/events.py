import asyncio
from typing import Any

# Each subscriber gets a queue
subscribers: list[asyncio.Queue] = []

def subscribe() -> asyncio.Queue:
    """Subscribe to events. Returns an asyncio.Queue that will receive events."""
    queue = asyncio.Queue()
    subscribers.append(queue)
    return queue

def unsubscribe(queue: asyncio.Queue) -> None:
    """Unsubscribe from events. Removes the given queue from the list of subscribers."""
    subscribers.remove(queue)

async def publish(event: dict) -> None:
    """Publish an event to all subscribers."""
    for queue in subscribers:
        await queue.put(event)