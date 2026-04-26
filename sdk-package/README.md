# QueueFlow SDK
Python SDK for the QueueFlow distributed task queue.

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
})

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

## Error Handling
```python
from queueflow_sdk import QueueFlowClient, ConflictError, NotFoundError

qf = QueueFlowClient("https://your-server.com", "your-api-key")

try:
    qf.cancel("nonexistent-task-id")
except NotFoundError:
    print("Task not found")
except ConflictError:
    print("Task already completed")
```