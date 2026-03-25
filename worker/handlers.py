import logging
import asyncio
from typing import Any

logger = logging.getLogger(__name__)

# Task registry - maps task_name strings to handler functions
TASK_REGISTRY: dict[str, Any] = {}

def register_task(task_name: str):
    """Decorator to register a function as a task handler."""
    def decorator(func):
        TASK_REGISTRY[task_name] = func
        logger.info(f"Registered task handler for '{task_name}'")
        return func
    return decorator

async def dispatch(task_name: str, payload: dict) -> dict:
    """ 
    Lookup and execute the handler for a given task_name.
    Retruns a result dict on success.
    Raises ValueError if no handler is registered.
    """
    handler = TASK_REGISTRY.get(task_name)
    
    if not handler:
        raise ValueError(f"No handler registered for task '{task_name}'")
    logger.info(f"Dispatching task '{task_name}' with payload: {payload}")
    result = await handler(payload)
    return result or {}

