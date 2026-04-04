import pytest

async def test_submit_task(client):
    """Test submitting a task through the API."""
    response = await client.post("/tasks/", json= {
        "task_name": "send_email",
        "payload": {"to": "test@example.com"},
        })
    assert response.status_code == 201
    data = response.json()
    assert data["task_name"] == "send_email"
    assert data["status"] == "queued"
    
async def test_list_tasks(client):
    """Test listing tasks through the API."""
    # First, submit a task to ensure there's at least one task in the system
    await client.post("/tasks/", json= {
        "task_name": "send_email",
        "payload": {"to": "test@example.com"}
        })
    # Then, list the tasks
    response = await client.get("/tasks/")
    assert response.status_code == 200
    data = response.json()
    assert len(data["tasks"]) >= 1
    assert data["tasks"][0]["task_name"] == "send_email"


async def test_get_task_status(client):
    """Test getting the status of a specific task."""
    # First, submit a task to get its ID
    response = await client.post("/tasks/", json= {
        "task_name": "send_email",
        "payload": {"to": "test@example.com"}
        })
    task_id = response.json()["id"]
    # Then, get the status of the task
    response = await client.get(f"/tasks/{task_id}")
    # Check that the response is successful and contains the correct task ID
    assert response.status_code == 200
    data = response.json()
    # Check that the task ID in the response matches the one we requested
    assert data["id"] == task_id

async def test_cancel_task(client):
    """Test canceling a specific task."""
    # First, submit a task to get its ID
    response = await client.post("/tasks/", json= {
        "task_name": "send_email",
        "payload": {"to": "test@example.com"}
        })
    task_id = response.json()["id"]
    # Then, cancel the task
    response = await client.post(f"/tasks/{task_id}/cancel")
    assert response.status_code == 200
    # Check status beomes FAILED after cancellation
    data = response.json()
    assert data["id"] == task_id
    assert data["status"] == "failed"


async def test_invalid_task_submission(client):
    """Test submitting a task with an invalid task name."""
    # Attempt to submit a task with an invalid name
    response = await client.post("/tasks/", json= {
        "task_name": "submit task",
        "payload": {}
        })
    # The API should return a 422 Unprocessable Entity status code for invalid input
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data
