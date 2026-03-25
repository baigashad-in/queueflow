import logging
import asyncio
from typing import Any

logger = logging.getLogger(__name__)

# Task registry - maps task_name strings to handler functions
TASK_REGISTRY: dict[str, Any] = {}

def register_task(task_name: str):
    """Decorator to register a task handler function."""
    def decorator(func):
        TASK_REGISTRY[task_name] = func
        logger.info(f"Registered task handler for '{task_name}'")
        return func
    return decorator