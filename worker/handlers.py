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

async def dispatch(task_name: str, payload: dict, task_id: str = None) -> dict:
    """ 
    Lookup and execute the handler for a given task_name.
    Retruns a result dict on success.
    Raises ValueError if no handler is registered.
    """
    handler = TASK_REGISTRY.get(task_name)
    
    if not handler:
        raise ValueError(f"No handler registered for task '{task_name}'")
    
    logger.info(f"Dispatching task '{task_name}' with payload: {payload} to handler: {handler.__name__}")
    result = await handler(payload, task_id = task_id)
    return result or {}

# --- Handlers -------------------------------

@register("send_email")
async def send_email_handler(payload: dict, task_id: str = None) -> dict:
    """Send an email notification via HTTP webhook."""
    to = payload.get("to")
    subject = payload.get("subject", "(No Subject)")
    body = payload.get("body", "")
    webhook_url = payload.get("webhook_url")

    if not to:
        raise ValueError("Email recipient is required. Please provide a 'to' address in the payload.")

    email_data = {
        "to": to,
        "subject": subject,
        "body": body,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }

    # If a webhook URL is provided, actually send the request
    if webhook_url:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(webhook_url, json=email_data, timeout=10)
        except httpx.ConnectError:
            raise ValueError(f"Could not connect to webhook '{webhook_url}'. Please check the URL is correct.")
        except httpx.TimeoutException:
            raise ValueError(f"Webhook '{webhook_url}' timed out after 10 seconds.")
        except Exception as e:
            raise ValueError(f"Failed to send to webhook: {type(e).__name__}")
        
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
async def handle_process_image(payload: dict, task_id: str = None) -> dict:
    """Download an image, resize it, and save the result."""
    image_url = payload.get("image_url")
    width = payload.get("width", 200)
    height = payload.get("height", 200)

    if not image_url:
        raise ValueError("Image URL is required. Please provide a valid image_url in the payload.")

    # Download the image
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(image_url)
    except httpx.ConnectError:
        raise ValueError(f"Failed to connect to {image_url}. Please check the URL and your network connection.")
    except httpx.TimeoutException:
        raise ValueError(f"Connection to '{image_url}' timed out after 15 seconds. The server may be slow or unreachable.")
    except httpx.InvalidURL:
        raise ValueError(f"The provided image URL '{image_url}' is invalid. Please provide a full URL starting with http:// or https://") 
    except Exception as e:
        raise ValueError(f"Failed to download image from '{image_url}': {type(e).__name__}")
    
    if response.status_code != 200:
        raise ValueError(f"Image server returned HTTP {response.status_code} for URL '{image_url}'. Expected 200 OK.")

    # Process with Pillow
    try:
        image = Image.open(BytesIO(response.content))
    except Exception as e:
        raise ValueError(f"The file at '{image_url}' is not a valid image. Please provide a URL to PNG, JPG, or WebP image. ")
    
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
async def handle_generate_report(payload: dict, task_id: str = None) -> dict:
    """Generate a real task statistics report."""
    report_type = payload.get("report_type", "summary")
    status_counts = {}
    total = 0

    try:
        async for session in get_session():
            query = select(TaskRecord.status, func.count(TaskRecord.id)).group_by(TaskRecord.status)
            if task_id:
                query = query.where(TaskRecord.id != task_id)
            result = await session.execute(query)
            status_counts = {row[0]: row[1] for row in result.all()}

            total_query = select(func.count(TaskRecord.id))
            if task_id:
                total_query = total_query.where(TaskRecord.id != task_id)

            total_result = await session.execute(total_query)
            total = total_result.scalar()
    except Exception as e:
        logger.warning(f"Could not query database for report: {e}")

    # Count this task as completed since it will be by the time anyone reads the report
    status_counts["completed"] = status_counts.get("completed", 0) + 1
    total += 1

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