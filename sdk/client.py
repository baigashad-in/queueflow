import httpx
import time
from typing import Optional

from sdk.models import Task, Tenant, ApiKey
from sdk.exceptions import QueueFlowError, AuthenticationError, NotFoundError, ConflictError


class QueueFlowClient:
    """Python SDK for QUeueFlow distributed task queue."""

    def __init__(self, url: str, api_key: str, timeout: int = 30):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.Client(
            base_url = self.url,
            headers = {"X-API-Key": self.api_key},
            timeout = self.timeout,
        )

    def _handle_error(self, response: httpx.Response):
        """Convert HTTP erros to SDK exceptions."""
        if response.status_code == 401:
            raise AuthenticationError("Invalid or missing API key", 401)
        if response.status_code == 404:
            detail = response.json().get("detail", "Resource not found")
            raise NotFoundError(detail, 404)
        if response.status_code == 409:
            detail = response.json().get("detail", "Action conflicts with current state")
            raise ConflictError(detail, 409)
        if not response.is_success:
            detail = response.json().get("detail", "Unknown error")
            raise QueueFlowError(detail, response.status_code)

    # --- Task operations ---

    def submit(
        self,
        task_name: str,
        payload: dict = None,
        priority: int = 5,
        max_retries: int = 3,
        delay_seconds: int = None,
        callback_url: str = None,
    ) -> Task:
        """Submit a new task."""
        body = {
            "task_name": task_name,
            "payload": payload or {},
            "priority": priority,
            "max_retries": max_retries,
        }
        if delay_seconds is not None:
            body["delay_seconds"] = delay_seconds
        if callback_url is not None:
            body["callback_url"] = callback_url

        response = self._client.post("/tasks/", json=body)
        self._handle_error(response)
        return Task.from_dict(response.json())

    def get_task(self, task_id: str) -> Task:
        """Get a task by ID."""
        response = self._client.get(f"/tasks/{task_id}")
        self._handle_error(response)
        return Task.from_dict(response.json())

    def list_tasks(self, status: str = None, page: int = 1, page_size: int = 20) -> tuple[list[Task], int]:
        """List tasks with optional status filter. Returns (tasks, total)."""
        params = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status

        response = self._client.get("/tasks/", params=params)
        self._handle_error(response)
        data = response.json()
        tasks = [Task.from_dict(t) for t in data["tasks"]]
        return tasks, data["total"]

    def cancel(self, task_id: str) -> Task:
        """Cancel a pending or queued task."""
        response = self._client.post(f"/tasks/{task_id}/cancel")
        self._handle_error(response)
        return Task.from_dict(response.json())

    def retry(self, task_id: str) -> Task:
        """Retry a failed or dead task."""
        response = self._client.post(f"/tasks/{task_id}/retry")
        self._handle_error(response)
        return Task.from_dict(response.json())

    def wait_for(self, task_id: str, poll_interval: float = 1.0, timeout: float = 300) -> Task:
        """Block until a task completes, fails, or times out."""
        start = time.time()
        while time.time() - start < timeout:
            task = self.get_task(task_id)
            if task.status in ("completed", "failed", "dead", "cancelled"):
                return task
            time.sleep(poll_interval)
        raise QueueFlowError(f"Task {task_id} did not complete within {timeout} seconds")

    # --- DLQ operations ---

    def list_dlq(self) -> list[Task]:
        """List all tasks in the dead letter queue."""
        response = self._client.get("/dlq")
        self._handle_error(response)
        return [Task.from_dict(t) for t in response.json()]

    def retry_all_dlq(self) -> dict:
        """Retry all tasks in the DLQ."""
        response = self._client.post("/dlq/retry-all")
        self._handle_error(response)
        return response.json()

    def purge_dlq(self) -> dict:
        """Permanently remove all tasks from the DLQ."""
        response = self._client.post("/dlq/purge")
        self._handle_error(response)
        return response.json()

    # --- Tenant operations (no auth required) ---

    @staticmethod
    def create_tenant(url: str, name: str) -> Tenant:
        """Create a new tenant. Does not require an API key."""
        response = httpx.post(f"{url}/tenants/", json={"name": name})
        if not response.is_success:
            detail = response.json().get("detail", "Failed to create tenant")
            raise QueueFlowError(detail, response.status_code)
        return Tenant.from_dict(response.json())

    @staticmethod
    def create_api_key(url: str, tenant_id: str, label: str = "default") -> ApiKey:
        """Create an API key for a tenant. Does not require an existing API key."""
        response = httpx.post(
            f"{url}/tenants/{tenant_id}/api-keys",
            json={"label": label},
        )
        if not response.is_success:
            detail = response.json().get("detail", "Failed to create API key")
            raise QueueFlowError(detail, response.status_code)
        return ApiKey.from_dict(response.json())

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close() 