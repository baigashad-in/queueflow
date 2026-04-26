from dataclasses import dataclass
from typing import Optional

@dataclass
class Task:
    """Represents a task returned from the API.
    
    Dataclass auto-generates __init__, __repr__, and __eq__
    from the field definitions. Users get IDE autocomplete
    and type checking for free.
    """
    id: str                             # UUID as string
    task_number: int                    # Human-readable sequential number
    task_name: str                      # Handler name: "send_email", "process_image", etc.
    payload: dict                       # The data passed to the handler
    priority: int                       # 1 = low, 5 = normal, 10 = high, 20 = critical
    status: str                         # "pending", "queued","running", "completed", "failed", "retrying", "dead"
    max_retries: int                    # Maximum retries allowed for this task
    retry_count: int                    # How many retires have been attempted so far
    max_results: Optional[dict]         # Result data after completion (None while running)
    error_message: Optional[str]        # Error details if failed/dead (None if successful)
    created_at: str                     # ISO timestamp when task was created
    updated_at: str                     # ISO timestamp of last status change
    started_at: Optional[str]           # ISO timestamp when processing began
    completed_at: Optional[str]         # ISO timestamp when processing completed (success or failure)
    callback_url: Optional[str] = None  # Webhook URL for completion notification

    @property
    def is_complete(self) -> bool:
        """Check if the task finished successfully."""
        return self.status == "completed"
    
    @property
    def is_failed(self) -> bool:
        """Check if the task failed permanently (failed or dead)."""
        return self.status in ("failed", "dead")
    
    @property
    def is_running(self) -> bool:
        """Check if the task is currently being processed."""
        return self.status == "running"

    @classmethod
    def from_dict(cls, data:dict) -> "Task":
        """Create a Task instance from a dictionary (e.g. API response).
        
        classmethod means you call it on the class, not an instance:
            task = Task.from_dict(api_response)
        
        Uses .get() with defaults for optional fields so missing
        keys don't crash — the API might not include null fields.

        """
        return cls(
            id = data["id"],
            task_number = data["task_number"],
            task_name = data["task_name"],
            payload = data["payload"],
            priority = data["priority"],
            status = data["status"],
            max_retries = data["max_retries"],
            retry_count = data["retry_count"],
            max_results = data.get("max_results"),
            error_message = data.get("error_message"),
            created_at = data["created_at"],
            updated_at = data["updated_at"],
            started_at = data.get("started_at"),
            completed_at = data.get("completed_at"),
            callback_url = data.get("callback_url"),
        )
    
@dataclass
class Tenant:
    """Represents a tenant (organization) in the Queueflow returned from the API."""
    id: str                        # UUID as string
    name: str                      # Tenant display name
    is_active: bool                # Whether the tenant can submit tasks
    created_at: str                # ISO timestamp when tenant was created


    @classmethod
    def from_dict(cls, data:dict) -> "Tenant":
        """Create a Tenant instance from a dictionary (e.g. API response)."""
        return cls(
            id = data["id"],
            name = data["name"],
            is_active = data["is_active"],
            created_at = data["created_at"],
        )
    
@dataclass
class ApiKey:
    """Represents an API key returned from the API."""
    id: str
    tenant_id: str
    key: str
    label: Optional[str]
    is_active: bool
    created_at: str

    @classmethod
    def from_dict(cls, data:dict) -> "ApiKey":
        """Create an ApiKey instance from a dictionary (e.g. API response)."""
        return cls(
            id = data["id"],
            tenant_id = data["tenant_id"],
            key = data["key"],
            label = data.get("label"),
            is_active = data["is_active"],
            created_at = data["created_at"],
        )