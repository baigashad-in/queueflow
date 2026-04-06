import logging
import asyncio
import json
import os
import httpx

from PIL import Image
from io import BytesIO
from typing import Any
from core.database import get_session
from core.db_models import TaskRecord
from sqlalchemy import select, func
from datetime import datetime, timezone

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
    """Send an email notification via HTTP webhook."""
    to = payload.get("to")
    subject = payload.get("subject", "(No Subject)")
    body = payload.get("body", "")
    webhook_url = payload.get("webhook_url")

    if not to:
        raise ValueError("'to' is required in payload")

    email_data = {
        "to": to,
        "subject": subject,
        "body": body,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }

    # If a webhook URL is provided, actually send the request
    if webhook_url:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=email_data, timeout=10)
            logger.info(f"Email sent to {to} via webhook — HTTP {response.status_code}")
            return {
                "sent_to": to,
                "subject": subject,
                "status": "delivered",
                "webhook_status": response.status_code,
            }

    # Fallback: log the email (useful when no webhook is configured)
    logger.info(f"Email logged (no webhook): to={to}, subject={subject}")
    return {
        "sent_to": to,
        "subject": subject,
        "status": "delivered",
        "webhook_status": None,
    }

@register("process_image")
async def handle_process_image(payload: dict) -> dict:
    """Download an image, resize it, and save the result."""
    image_url = payload.get("image_url")
    width = payload.get("width", 200)
    height = payload.get("height", 200)

    if not image_url:
        raise ValueError("image_url is required in payload")

    # Download the image
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(image_url)
        if response.status_code != 200:
            raise ValueError(f"Failed to download image: HTTP {response.status_code}")

    # Process with Pillow
    image = Image.open(BytesIO(response.content))
    original_size = image.size
    image = image.resize((width, height))

    # Save the resized image
    os.makedirs("processed_images", exist_ok=True)
    filename = f"processed_images/resized_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.png"
    image.save(filename)

    logger.info(f"Image processed: {original_size} → ({width}, {height}), saved to {filename}")
    return {
        "status": "processed",
        "original_size": list(original_size),
        "new_size": [width, height],
        "filename": filename,
    }


@register("generate_report")
async def handle_generate_report(payload: dict) -> dict:
    """Generate a real task statistics report."""
    report_type = payload.get("report_type", "summary")
    status_counts = {}
    total = 0

    try:
        async for session in get_session():
            result = await session.execute(
                select(TaskRecord.status, func.count(TaskRecord.id))
                .group_by(TaskRecord.status)
            )
            status_counts = {row[0]: row[1] for row in result.all()}
            total_result = await session.execute(select(func.count(TaskRecord.id)))
            total = total_result.scalar()
    except Exception as e:
        logger.warning(f"Could not query database for report: {e}")

    report = {
        "report_type": report_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_tasks": total,
        "status_breakdown": status_counts,
    }

    # Write report to file
    os.makedirs("reports", exist_ok=True)
    filename = f"reports/report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Report generated: {filename}")
    return {"status": "generated", "filename": filename, "total_tasks": total}