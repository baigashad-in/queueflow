import time
import uuid
import logging
import json
import os
import tempfile

from fpdf import FPDF

from typing import Optional
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from core.database import get_session 
from core.models import TaskStatus
from core.queue import push_task
from core.metrics import tasks_submitted_total
from core.scheduler import schedule_task
from core.events import publish_task_event
from core.db_models import Tenant, TaskRecord

from api.auth import get_current_tenant
from api.schemas import TaskSubmitRequest, TaskResponse, TaskListResponse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from repositories.task_repo import get_by_id, get_by_tenant

router = APIRouter(prefix = "/tasks", tags = ["Tasks"])
logger = logging.getLogger(__name__)

@router.post("/", response_model = TaskResponse, status_code = 201)
async def submit_task(
    request: TaskSubmitRequest,
    tenant: Tenant = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    """
    Submit a new task to the queue.
    """

    task = TaskRecord(
        task_name = request.task_name,
        payload = request.payload,
        priority = request.priority.value,
        max_retries = request.max_retries,
        status = TaskStatus.PENDING,
        tenant_id = tenant.id,
    )

    session.add(task)
    await session.commit()
    await session.refresh(task)

    # Record submission metric
    tasks_submitted_total.labels(
        task_name = task.task_name,
        priority = str(task.priority),
    ).inc()

    if request.delay_seconds is not None:
        run_at = time.time() + request.delay_seconds
        await schedule_task(str(task.id), run_at)
        logger.info(f"Task scheduled with delay: {task.id} to run at {request.delay_seconds} seconds from now")
        task.status = TaskStatus.PENDING
    else:
        # Push into Redis priority queue
        # Update status to QUEUED after pushing to Redis
        await push_task(str(task.id), task.priority)
        task.status = TaskStatus.QUEUED
        logger.info(f"Task queued: {task.id} [{task.task_name}] priority={task.priority}")

    await session.commit()
    await publish_task_event(task) # Publish event after task is submitted and status is updated
    await session.refresh(task)
    return task

@router.get("/", response_model = TaskListResponse)
async def list_tasks(
    status: Optional[TaskStatus] = Query(None, description="Filter tasks by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    tenant: Tenant = Depends(get_current_tenant),
):
    """List all tasks with optional status filter and pagination."""

    # Fetch tasks for the tenant with pagination
    tasks, total = await get_by_tenant(
        session, tenant.id,
        status=status.value if status else None,
        page=page, page_size=page_size,
    )

    return TaskListResponse(tasks=tasks, total=total, page=page, page_size=page_size)

@router.get("/{task_id}", response_model = TaskResponse)
async def get_task(
    task_id: str, 
    session: AsyncSession = Depends(get_session),
    tenant: Tenant = Depends(get_current_tenant),
    ):
    """Get details of a specific task by ID."""
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")
    task = await get_by_id(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/download", response_class=FileResponse)
async def download_report(
    task_id: str,
    session: AsyncSession = Depends(get_session),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Download the result file for a completed task as PDF."""
    task = await get_by_id(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="Task is not completed")

    result = task.max_results or {}
    filename = result.get("filename")
    if not filename or not os.path.exists(filename):
        raise HTTPException(status_code=404, detail="No file available for download")

    # Read the JSON report
    with open(filename, "r") as f:
        report_data = json.load(f)

    # Build PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 15, "QueueFlow Report", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, f"Report Type: {report_data.get('report_type', 'N/A')}", ln=True)
    pdf.cell(0, 8, f"Generated At: {report_data.get('generated_at', 'N/A')}", ln=True)
    pdf.cell(0, 8, f"Total Tasks: {report_data.get('total_tasks', 0)}", ln=True)
    pdf.ln(5)

    # Status breakdown table
    status_breakdown = report_data.get("status_breakdown", {})
    if status_breakdown:
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "Status Breakdown", ln=True)
        pdf.ln(3)

        pdf.set_font("Helvetica", "B", 11)
        pdf.set_fill_color(40, 40, 60)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(95, 10, "Status", border=1, fill=True)
        pdf.cell(95, 10, "Count", border=1, fill=True, ln=True)

        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(0, 0, 0)
        for status, count in status_breakdown.items():
            pdf.cell(95, 9, str(status).upper(), border=1)
            pdf.cell(95, 9, str(count), border=1, ln=True)

    # Save to temp file
    pdf_path = tempfile.mktemp(suffix=".pdf")
    pdf.output(pdf_path)

    return FileResponse(
        path=pdf_path,
        filename=f"queueflow_report_{task_id[:8]}.pdf",
        media_type="application/pdf",
    )