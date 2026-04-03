import pytest

from api.schemas import TaskSubmitRequest
from core.models import TaskPriority

async def test_valid_task_request():
    request = TaskSubmitRequest(
        task_name = "send_email",
        payload = {"to": "test@example.com"},
        priority = TaskPriority.HIGH,
        max_retries = 3
    )
    assert request.task_name == "send_email"
    assert request.priority == TaskPriority.HIGH


async def test_task_name_invalid_characters():          
    """Task names with invalid characters should be rejected."""
    with pytest.raises(ValueError):
        TaskSubmitRequest(
            task_name = "send-email!", # invalid characters
        )


async def test_task_name_with_spaces():
    """Task names with spaces should be rejected."""
    with pytest.raises(ValueError):
        TaskSubmitRequest(
            task_name = "send email", # contains space
        )

async def test_task_name_too_long():    
    """Task names longer than 50 characters should be rejected."""
    with pytest.raises(ValueError):
        TaskSubmitRequest(
            task_name = "a" * 256,
        )

async def test_valid_task_request_normal_priority():
    """Test that a valid task request with normal priority is accepted."""
    request = TaskSubmitRequest(
        task_name = "send_email",
        payload = {"to": "test@example.com"},
        priority = TaskPriority.NORMAL,
        max_retries = 8
    )
    assert request.task_name == "send_email"
    assert request.priority == TaskPriority.NORMAL

async def test_valid_task_request_low_priority():
    """Test that a valid task request with low priority is accepted."""
    request = TaskSubmitRequest(
        task_name = "send_email",
        payload = {"to": "test@example.com"},
        priority = TaskPriority.LOW,
        max_retries = 5
    )
    assert request.task_name == "send_email"
    assert request.priority == TaskPriority.LOW

async def test_valid_task_request_no_priority():
    """Test that a valid task request with no priority defaults to normal."""
    request = TaskSubmitRequest(
        task_name = "send_email",
        payload = {"to": "test@example.com"},
        max_retries = 8
    )
    assert request.task_name == "send_email"
    assert request.priority == TaskPriority.NORMAL  


async def test_task_name_empty():
    """Task names cannot be empty."""
    with pytest.raises(ValueError):
        TaskSubmitRequest(
            task_name = "",
        )

async def test_task_name_gets_lowercased():
    """Task names gets converted to lowercase."""
    request = TaskSubmitRequest(
        task_name = "Send_Email",
        payload = {"to": "test@example.com"},
        max_retries = 6
    )
    assert request.task_name == "send_email"
