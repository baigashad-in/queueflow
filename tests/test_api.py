from httpx import AsyncClient, ASGITransport
from api.main import app
from core.database import get_session

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

async def test_missing_api_key(test_session, test_tenant, engine):
    """Requests without API key should be rejected."""
    async def override_get_session():
        yield test_session

    # Override the get_session dependency to use the test session
    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app= app)

    # Make a request without the API key
    async with AsyncClient(transport = transport, base_url = "http://test") as no_auth_client:
        response = await no_auth_client.post("/tasks/", json = {
            "task_name": "send_email",
            "payload": {},
        })

    app.dependency_overrides.clear()
    assert response.status_code == 401 # Missing API key returns Unauthorized

async def test_wrong_api_key(test_session, test_tenant, engine):
    """Requests with invalid API key should be rejected."""

    async def override_get_session():
        yield test_session

    # Override the get_session dependency to use the test session
    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app = app)

    # Make a request with an incorrect API key
    async with AsyncClient(
        transport = transport,
        base_url = "http://test",
        headers = {"X-API-Key": "totally-wrong-key"},
    ) as bad_client:
        response = await bad_client.post("/tasks/", json = {
            "task_name": "send_email",
            "payload": {},
        })
    app.dependency_overrides.clear()
    assert response.status_code == 401


async def test_invalid_uuid_format(client):
    """Test that an invalid UUID format returns an error."""
    response = await client.get("/tasks/not-a-uuid")
    assert response.status_code == 400 # FastAPI returns 400 for invalid path parameter formats


async def test_get_nonexistent_task(client):
    """Test getting a task that doesn't exist."""
    response = await client.get("/tasks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404 # FastAPI returns 404 for valid UUIDs that don't correspond to any task


async def test_cancel_already_cancelled_task(client):
    """Cancelling an already-cancelled task should return 409."""
    response = await client.post("/tasks/", json = {
        "task_name": "send_email", 
        "payload": {}
        })
    task_id = response.json()["id"]

    await client.post(f"/tasks/{task_id}/cancel")
    response = await client.post(f"/tasks/{task_id}/cancel")

    assert response.status_code == 409 # Conflict for already cancelled task


async def test_cancel_invalid_task_id(test_session, test_tenant, engine):
    """Test canceling a task with an invalid task ID."""
    
    async def override_get_session():
        yield test_session
    
    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app = app)

    # Attempt to cancel a task with an invalid ID
    async with AsyncClient(transport = transport, 
                           base_url = "http://test",
                           headers = {"X-API-Key": "api_key"}) as client:
        response = await client.post("/tasks/invalid-id/cancel")

    app.dependency_overrides.clear()
    assert response.status_code == 404 # Not Found for invalid task ID


async def test_submit_task_with_delay(client):
    """Test submitting a task with a delay."""
    response = await client.post("/tasks/", json={
        "task_name": "send_email",
        "payload": {"to": "test@example.com"},
        "delay_seconds": 30,
    })

    assert response.status_code == 201

    assert response.json()["status"] == "pending" # Tasks with a future execution time should be in "pending" status

async def test_submit_task_with_max_retries(client):
    """Test submitting a task with a specific maximum number of retries."""
    response = await client.post("/tasks/", json={
        "task_name": "send_email",
        "payload": {},
        "max_retries": 0,
    })

    assert response.status_code == 201

    assert response.json()["max_retries"] == 0 # The task should be created with the specified max_retries value

