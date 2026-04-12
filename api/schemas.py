from pydantic import BaseModel, Field, field_validator
from typing import Any, Optional
from datetime import datetime
from uuid import UUID
import re 

from core.models import TaskPriority, TaskStatus


class TaskSubmitRequest(BaseModel):
    """What the client sends when submitting a task."""
    task_name: str = Field(
        ...,
        min_length = 1,
        max_length = 255,
        description = "Name of the rask to execute",
        examples = ["send_email", "process_image", "generate_report"]
    )
    payload: dict[str, Any] = Field(
        default_factory= dict,
        description = "Data the task needs to execute"
    )
    priority: TaskPriority = Field(
        default = TaskPriority.NORMAL,
        description="Task priority. Higher = processed first"
    )
    max_retries: int = Field(
        default = 3,
        ge = 0,
        le = 10,
        description = "Maximum retry attempts on failure"
    )

    delay_seconds: Optional[int] = Field(
        default = None,
        ge = 0,
        description = "Delay in seconds before the task is executed/run"
    )

    cron_expression : Optional[str] = Field(
        default = None,
        description = "Cron expression for recurring tasks at scheduled time. Overrides delay_seconds if both are provided."
    )



    @field_validator("task_name")
    @classmethod
    def task_name_no_spaces(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError("task_name cannot contain spaces or hyphens. Use underscores: like 'send_email'")
        return v.lower()
    

class TaskResponse(BaseModel):
    """What we return after a task is created."""
    task_number: int
    id: UUID
    task_name: str
    payload: dict[str, Any]
    priority: int
    status: TaskStatus
    max_retries: int
    retry_count: int
    max_results: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at : Optional[datetime] = None

    model_config = {"from_attributes": True}
     

class TaskListResponse(BaseModel):
    """Paginated list of tasks."""
    tasks: list[TaskResponse]
    total: int
    page: int
    page_size:int


class TenantCreateRequest(BaseModel):
    name: str = Field(..., min_length = 1, max_length = 255)

class TenantResponse(BaseModel):
    id: UUID
    name: str
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class ApiKeyCreateRequest(BaseModel):
    label: str = Field(default = None, max_length = 255)

class ApiKeyResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    key: str
    label: str | None
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}
