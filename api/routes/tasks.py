from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import logging



from core.database import get_session, TaskRecord
from core.models import TaskStatus
from api.schemas import TaskSubmitRequest, TaskResponse, TaskListResponse

router = APIRouter(prefix = "/tasks", tags = ["Tasks"])
logger = logging.getlogger(__name__)

@router.post("/", response_model = TaskResponse, status_code = 201)
async def submit_task(
    request: TaskSubmitRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Submit a new task to the queue.
    The task is saved tot he database with PENDING status.

    In Phase 3, this will also push the task into the Redis queue.
    """

task = TaskRecord(
    task_name = request.task_name,
    payload = request.payload,
    priority = request.priority.value,
    max_retries = request.max_retries,
    status = TaskStatus.PENDING,
)

    