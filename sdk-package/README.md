# QueueFlow SDK
Python SDK for the [QueueFlow](https://github.com/baigashad-in/queueflow) distributed task queue.

QueueFlow is a production-grade task queue built with Python, FastAPI, Redis, and PostgreSQL. It supports priority queues, retry with exponential backoff, dead letter queues, scheduled tasks, multi-tenant isolation, and real-time WebSocket updates.


## Installation
```bash
pip install queueflow-sdk
```

## Quick Start
```python
from queueflow_sdk import QueueFlowClient

# Create a tenant and get an API key
tenant = QueueFlowClient.create_tenant("https://your-server.com", "Company Name")
key = QueueFlowClient.create_api_key("https://your-server.com", tenant.id)

# Initialize the client
qf = QueueFlowClient("https://your-server.com", key.key)

# Submit a task
task = qf.submit("send_email", payload = {
    "to": "user@example.com",
    "subject": "Hello from QueueFlow",
    "body": "This was sent via the SDK",
})
print(f"Task {task.id} status: {task.status}")

# Wait for completion
result = qf.wait_for(task.id)
print(result.status) # "completed"
print(result.max_results) # {"sent_to": "user@example.com", ...}

# Always close when done
qf.close()
```

## Context Manager
```python
with QueueFlowClient("https://your-server.com", "your-api-key") as qf:
    task = qf.submit("process_image", payload = {
        "image_url": "https://example.com/photo.jpg",
        "width": 400,
        "height": 300,
    })
    result = qf.wait_for(task.id)
```

## All Operations

### Task Management

```python
# Submit with priority and delay
task = qf.submit(
    "send_email",
    payload={"to": "user@example.com"},
    priority=10,          # 1=low, 5=normal, 10=high, 20=critical
    max_retries=3,
    delay_seconds=60,     # Wait 60 seconds before processing
    callback_url="https://your-app.com/webhook",  # POST result on completion
)

# Get task status
task = qf.get_task("task-uuid-here")
print(task.status)        # "completed"
print(task.is_complete)   # True
print(task.is_failed)     # False

# List tasks with filtering
tasks, total = qf.list_tasks(status="completed", page=1, page_size=20)

# Cancel a pending task
cancelled = qf.cancel("task-uuid-here")

# Retry a failed task
retried = qf.retry("task-uuid-here")

# Block until a task finishes
result = qf.wait_for("task-uuid-here", poll_interval=1.0, timeout=300)
```

### Dead Letter Queue

```python
# List dead tasks
dead_tasks = qf.list_dlq()

# Retry all dead tasks
qf.retry_all_dlq()

# Purge the DLQ (cannot be undone)
qf.purge_dlq()
```

## Error Handling
```python
from queueflow_sdk import (
    QueueFlowClient,
    AuthenticationError,
    NotFoundError,
    ConflictError,
    QueueFlowError,
)

qf = QueueFlowClient("https://your-server.com", "your-api-key")

try:
    qf.cancel("nonexistent-task-id")
except NotFoundError:
    print("Task not found")
except ConflictError:
    print("Task already completed — cannot cancel")
except AuthenticationError:
    print("Invalid API key")
except QueueFlowError as e:
    print(f"Error {e.status_code}: {e.message}")
```

## Task Types

QueueFlow includes three built-in task handlers:

| Task Name | Payload | Description |
|-----------|---------|-------------|
| `send_email` | `to`, `subject`, `body` | Logs email or sends to a webhook |
| `process_image` | `image_url`, `width`, `height` | Downloads and resizes an image |
| `generate_report` | `report_type` | Generates a task summary report as PDF |

Custom handlers can be added by registering functions with the `@register` decorator in the worker.

## Links

- **GitHub:** https://github.com/baigashad-in/queueflow
- **Live Demo:** https://queueflow.swedencentral.cloudapp.azure.com/dashboard/
- **API Docs:** https://queueflow.swedencentral.cloudapp.azure.com/docs