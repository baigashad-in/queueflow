import pytest
from worker.handlers import dispatch, TASK_REGISTRY

async def test_send_email_handler():
    """Test the send_email handler."""
    result = await dispatch("send_email", {
        "to": "test@example.com",
        "subject": "Hello",
    })
    assert result["status"] == "delivered"
    assert result["sent_to"] == "test@example.com"

async def test_process_image_handler():
    """Test the process_image handler."""
    result = await dispatch("process_image", {
        "image_url": "https://picsum.photos/200/200",
        "width": 100,
        "height": 100,
    })
    assert result["status"] == "processed"
    assert result["new_size"] == [100, 100]

async def test_generate_report_handler():
    """Test the generate_report handler."""
    result = await dispatch("generate_report", {
        "report_type": "summary",
    })
    assert result["status"] == "generated"
    assert "filename" in result

async def test_unknown_handler_raises():
    """Dispatching a task with an unknown name should raise an error."""
    with pytest.raises(ValueError):
        await dispatch("non_existent_task", {})

async def test_all_handlers_registered():
    """Test that all handlers are registered in the task registry."""
    assert "send_email" in TASK_REGISTRY
    assert "process_image" in TASK_REGISTRY
    assert "generate_report" in TASK_REGISTRY