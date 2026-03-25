import logging
import asyncio
from typing import Any

logger = logging.getLogger(__name__)

# Task registry - maps task_name strings to handler functions
TASK_REGISTRY: dict[str, Any] = {}

def register(task_name: str):
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
    
    logger.info(f"Dispatching task '{task_name}' with payload: {payload} to handler: {handler.__name__}")
    result = await handler(payload)
    return result or {}

# --- Handlers -------------------------------

@register("send_email")
async def send_email_handler(payload: dict) -> dict:
    """Simulate sending an email."""
    to = payload.get("to", "unknown")
    subject = payload.get("subject", "(No Subject)")
    logger.info(f"Sending email to {to} - Subject: {subject}")
    await asyncio.sleep(0.5)  # Simulate netwrok call
    return {"sent_to": to, "subject": subject, "status": "delivered"}

@register("process_image")
async def handle_process_image(payload: dict) -> dict:
    """Simulate processing an image."""
    image_url = payload.get("image_url", "unknown")
    operation = payload.get("operation", "resize")
    logger.info(f"Processing image from {image_url} - Operation: {operation}")
    await asyncio.sleep(1)  # Simulate CPU work
    return {"image_url": image_url, "operation": operation, "status": "processed"}


@register("generate_report")
async def handle_generate_report(payload: dict) -> dict:
    """Simulate generating a report."""
    report_type = payload.get("report_type", "summary")
    logger.info(f"Generating report - Type: {report_type}")
    await asyncio.sleep(1.5)  # Simulate heavy work    
    return {"report_type": report_type,"pages":4, "status": "generated"}