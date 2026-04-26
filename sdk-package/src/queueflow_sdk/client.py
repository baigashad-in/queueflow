import httpx
import time
from typing import Optional

from queueflow_sdk.models import Task, Tenant, ApiKey
from queueflow_sdk.exceptions import QueueFlowError, AuthenticationError, NotFoundError, ConflictError


class QueueFlowClient:
    """Python SDK for QueueFlow distributed task queue.
    
    Usage:
        qf = QueueFlowClient("https://your-server.com", "your-api-key")
        task = qf.submit("send_email", payload={"to": "user@example.com"})
        result = qf.wait_for(task.id)
        print(result.status)  # "completed"
    
    Context manager usage (auto-closes the HTTP connection):
        with QueueFlowClient("https://your-server.com", "your-api-key") as qf:
            task = qf.submit("send_email", payload={"to": "user@example.com"})

    """

    def __init__(self, url: str, api_key: str, timeout: int = 30):
        """Initialize the client.
        
        Args:
            url: Base URL of the QueueFlow API (e.g. "https://queueflow.example.com")
            api_key: Your API key for authentication
            timeout: Request timeout in seconds (default 30)
        """
        self.url = url.rstrip("/") # rstrip("/") removes trailing slash to prevent double slashes in URLs
        self.api_key = api_key
        self.timeout = timeout

        # httpx.Client is a persistent HTTP connection pool.
        # base_url means every request URL is relative to this.
        # headers are sent with every request automatically.
        # More efficient than creating a new connection per request.
        self._client = httpx.Client(
            base_url = self.url,
            headers = {"X-API-Key": self.api_key},
            timeout = self.timeout,
        )

    def _handle_error(self, response: httpx.Response):
        """Convert HTTP error responses to typed Python exceptions.
        
        Instead of checking response.status_code everywhere,
        every method calls this once. Centralizes error handling.
        
        Args:
            response: The HTTP response to check
            
        Raises:
            AuthenticationError: If 401 (bad/missing API key)
            NotFoundError: If 404 (resource doesn't exist)
            ConflictError: If 409 (action conflicts with current state)
            QueueFlowError: For any other non-success status code
        """
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
        """Submit a new task for processing.
        
        Args:
            task_name: Handler to run (e.g. "send_email", "process_image")
            payload: Data passed to the handler (default empty dict)
            priority: 1=low, 5=normal, 10=high, 20=critical (default 5)
            max_retries: How many times to retry on failure (default 3)
            delay_seconds: Wait this many seconds before processing (optional)
            callback_url: URL to POST results to when task completes (optional)
            
        Returns:
            Task object with status "queued" or "pending"
            
        Raises:
            AuthenticationError: If API key is invalid
            QueueFlowError: If submission fails
        """
        body = {
            "task_name": task_name,
            "payload": payload or {},  # "payload or {}" means: if payload is None, use empty dict
            "priority": priority,
            "max_retries": max_retries,
        }
        if delay_seconds is not None:
            body["delay_seconds"] = delay_seconds
        if callback_url is not None:
            body["callback_url"] = callback_url

        # POST to /tasks/ endpoint
        response = self._client.post("/tasks/", json=body)
        # Check for errors (401, 404, 409, etc.)
        self._handle_error(response)
        # Parse the JSON response into a Task object
        return Task.from_dict(response.json())

    def get_task(self, task_id: str) -> Task:
        """Get the current state of a task by its ID.
        
        Args:
            task_id: UUID of the task
            
        Returns:
            Task object with current status and results
            
        Raises:
            NotFoundError: If task doesn't exist
        """
        response = self._client.get(f"/tasks/{task_id}")
        self._handle_error(response)
        return Task.from_dict(response.json())

    def list_tasks(self, status: str = None, page: int = 1, page_size: int = 20) -> tuple[list[Task], int]:
        """List tasks with optional filtering and pagination.
        
        Args:
            status: Filter by status (e.g. "completed", "failed")
            page: Page number (default 1)
            page_size: Tasks per page (default 20)
            
        Returns:
            Tuple of (list of Task objects, total count)
            The total count is across all pages, not just this page.
        """

        # Build query parameters
        params = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status

        response = self._client.get("/tasks/", params=params)
        self._handle_error(response)
        data = response.json()
        tasks = [Task.from_dict(t) for t in data["tasks"]]
        return tasks, data["total"]

    def cancel(self, task_id: str) -> Task:
        """Cancel a pending or queued task.
        
        Args:
            task_id: UUID of the task to cancel
            
        Returns:
            Updated Task object
            
        Raises:
            ConflictError: If task is already running/completed/failed
            NotFoundError: If task doesn't exist
        """
        response = self._client.post(f"/tasks/{task_id}/cancel")
        self._handle_error(response)
        return Task.from_dict(response.json())

    def retry(self, task_id: str) -> Task:
        """Retry a failed or dead task.
        
        Args:
            task_id: UUID of the task to retry
            
        Returns:
            Updated Task object with status "queued"
            
        Raises:
            ConflictError: If task is not in a retriable state
            NotFoundError: If task doesn't exist
        """
        response = self._client.post(f"/tasks/{task_id}/retry")
        self._handle_error(response)
        return Task.from_dict(response.json())

    def wait_for(self, task_id: str, poll_interval: float = 1.0, timeout: float = 300,) -> Task:
        """Block until a task reaches a terminal state.
        
        Polls the API every poll_interval seconds until the task
        is completed, failed, dead, or cancelled. Raises an error
        if the timeout is exceeded.
        
        Args:
            task_id: UUID of the task to wait for
            poll_interval: Seconds between status checks (default 1.0)
            timeout: Maximum seconds to wait (default 300 = 5 minutes)
            
        Returns:
            Task object in its final state
            
        Raises:
            QueueFlowError: If timeout is exceeded
        """

        # Record when we started waiting
        start = time.time()

        # Loop until timeout
        while time.time() - start < timeout:
            task = self.get_task(task_id)
            if task.status in ("completed", "failed", "dead", "cancelled"):
                return task
            
            # Sleep before checking again to avoid hammering the API
            time.sleep(poll_interval)

        # If we get here, the timeout expired
        raise QueueFlowError(f"Task {task_id} did not complete within {timeout} seconds")

    # --- DLQ operations ---

    def list_dlq(self) -> list[Task]:
        """List all tasks in the dead letter queue.
        
        Returns:
            List of Task objects that exhausted all retries
        """
        response = self._client.get("/dlq")
        self._handle_error(response)
        return [Task.from_dict(t) for t in response.json()]

    def retry_all_dlq(self) -> dict:
        """Retry all tasks in the DLQ.
        
        Returns:
            Dict with "replayed" (count of retried) and "failed" keys
        """
        response = self._client.post("/dlq/retry-all")
        self._handle_error(response)
        return response.json()

    def purge_dlq(self) -> dict:
        """Permanently remove all tasks from the DLQ.
        
        Warning: This cannot be undone. Task records remain in the
        database but can no longer be retried from the DLQ.
        
        Returns:
            Dict with confirmation message
        """
        response = self._client.post("/dlq/purge")
        self._handle_error(response)
        return response.json()

    # --- Tenant operations (no auth required) ---

    @staticmethod
    def create_tenant(url: str, name: str) -> Tenant:
        """Create a new tenant. Does not require an API key.
        
        This is a static method — you call it on the class, not an instance:
            tenant = QueueFlowClient.create_tenant("https://server.com", "My Company")
        
        It's static because you don't have an API key yet —
        you're creating a tenant to GET an API key.
        
        Args:
            url: Base URL of the QueueFlow API
            name: Display name for the tenant
            
        Returns:
            Tenant object with id, name, etc.
        """

        # Use a one-off httpx.post() instead of self._client
        # because we don't have an API key to put in the header yet.
        response = httpx.post(f"{url}/tenants/", json={"name": name})
        if not response.is_success:
            detail = response.json().get("detail", "Failed to create tenant")
            raise QueueFlowError(detail, response.status_code)
        return Tenant.from_dict(response.json())

    @staticmethod
    def create_api_key(url: str, tenant_id: str, label: str = "default") -> ApiKey:
        """Create an API key for a tenant. Does not require an existing API key.
        
        Args:
            url: Base URL of the QueueFlow API
            tenant_id: UUID of the tenant
            label: Human-readable label for the key (default "default")
            
        Returns:
            ApiKey object containing the key string
        """
        response = httpx.post(
            f"{url}/tenants/{tenant_id}/api-keys",
            json={"label": label},
        )
        if not response.is_success:
            detail = response.json().get("detail", "Failed to create API key")
            raise QueueFlowError(detail, response.status_code)
        return ApiKey.from_dict(response.json())

    def close(self):
        """Close the HTTP client and release connections.
        
        Always call this when you're done, or use the context manager:
            with QueueFlowClient(...) as qf:
                ...  # auto-closes when the block exits
        """
        self._client.close()

    def __enter__(self):
        """Support 'with' statement — returns the client instance."""
        return self

    def __exit__(self, *args):
        """Support 'with' statement — closes the client on exit.
        
        *args captures the exception info (type, value, traceback)
        that Python passes to __exit__. We don't use them because
        we always want to close the connection, even on errors.
        """
        self.close() 