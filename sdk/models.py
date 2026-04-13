from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class Task:
    """Represents a task returned from the API."""
    id: str
    task_number: int
    task_name: str
    payload: dict
    priority: int
    status: str
    max_retries: int
    retry_count: int
    max_results: Optional[dict]
    error_message: Optional[str]
    created_at: str
    updated_at: str
    started_at: Optional[str]
    completed_at: Optional[str]

    @property
    def is_complete(self) -> bool:
        return self.status == "completed"
    
    @property
    def is_failed(self) -> bool:
        return self.status in ("failed", "dead")
    
    @classmethod
    def from_dict(cls, data:dict) -> "Task":
        """Create a Task instance from a dictionary (e.g. API response)."""
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
            completed_at = data.get("completed_at")
        )
    
@dataclass
class Tenant:
    """Represents a tenant returned from the API."""
    id: str
    name: str
    is_active: bool
    created_at: str

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