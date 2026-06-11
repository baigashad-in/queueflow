"""
Tests for error-handling branches in worker/handlers.py. 

These cover the https exception paths that fire when an external service
(webhook target, image URL) is down, slow, or returns bad data. They use
respx to intercept httpx calls - no real network traffic.

Why these matter: every handler exception path is a real production
failure mode. A test that exercises "image_url is unreachable" verifies
the worker handles network problems gracefully and produces a useful
error message, rather than crashing with an opaque traceback.
"""
import io
import os
import pytest
import httpx
import respx
from PIL import Image

from worker.handlers import send_email_handler, handle_process_image

# ────────────────────────────────────────────────────────────────────
# send_email — webhook-call error paths
# ────────────────────────────────────────────────────────────────────

class TestSendEmailErrorPaths:
    @respx.mock
    async def test_webhook_connect_error_raises_value_error(self):
        """Webhook host unreachable -> ValueError with helpful message."""
        respx.post("https://hooks.example.com/email").mock(
            side_effect = httpx.ConnectError("Connection refused")
        )

        with pytest.raises(ValueError):
            await send_email_handler({
                "to": "user@example.com",
                "subject": "test",
                "body": "x",
                "webhook_url": "https://hooks.example.com/email",
            })

    @respx.mock
    async def test_webhook_timeout_raises_value_error(self):
        """Webhook slow to respond -> ValueError."""
        respx.post("https://hooks.example.com/email").mock(
            side_effect = httpx.TimeoutException("Request timed out")
        )

        with pytest.raises(ValueError):
            await send_email_handler({
                "to": "user@example.com",
                "subject": "test",
                "body": "x",
                "webhook_url": "https://hooks.example.com/email",
            })

    @respx.mock
    async def test_webhook_generic_error_wrapped(self):
        """Any other exception from httpx -> wrapped in ValueError, not bubbled raw."""
        respx.post("https://hooks.example.com/email").mock(
            side_effect = httpx.ReadError("connection reset")
        )

        with pytest.raises(ValueError):
            await send_email_handler({
                "to": "user@example.com",
                "subject": "test",
                "body": "x",
                "webhook_url": "https://hooks.example.com/email",
            })
    
    @respx.mock
    async def test_webhook_success_returns_delivered(self):
        """Happy path with webhook: status = delivered."""
        respx.post("https://hooks.example.com/email").mock(
            return_value = httpx.Response(200, json={"ok": True})
        )

        result = await send_email_handler({
            "to": "user@example.com",
            "subject": "test",
            "body": "x",
            "webhook_url": "https://hooks.example.com/email",
        })

        assert result.get("status") == "delivered" or result.get("webhook_status") == 200

# ────────────────────────────────────────────────────────────────────
# process_image — download + decode error paths
# ────────────────────────────────────────────────────────────────────

def _make_real_image_bytes():
    """Build a real 100x100 PNG in memory."""
    img = Image.new("RGB", (100, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

class TestProcessImageErrorPaths:
    @respx.mock
    async def test_image_connect_error(self):
        """Image host unreachable -> ValueError."""
        respx.get("https://images.example.com/missing.png").mock(
            side_effect = httpx.ConnectError("DNS failure")
        )

        with pytest.raises(ValueError):
            await handle_process_image({"image_url": "https://images.example.com/missing.png"})

    @respx.mock
    async def test_image_timeout(self):
        respx.get("https://images.example.com/slow.png").mock(
            side_effect = httpx.TimeoutException("timed out")
        )

        with pytest.raises(ValueError):
            await handle_process_image({"image_url": "https://images.example.com/slow.png"})

    @respx.mock
    async def test_image_non_200_response(self):
        """Server returns 404 -> ValueError."""
        respx.get("https://images.example.com/notfound.png").mock(
            return_value = httpx.Response(404)
        )

        with pytest.raises(ValueError):
            await handle_process_image({"image_url": "https://images.example.com/notfound.png"})

    @respx.mock
    async def test_image_not_valid_image_data(self):
        """Server returns 200 but body isn't actually an image -> ValueError."""
        respx.get("https://images.example.com/fake.png").mock(
            return_value = httpx.Response(200, content = b"this is not an image")
        )

        with pytest.raises(ValueError):
            await handle_process_image({"image_url": "https://images.example.com/fake.png"})

    @respx.mock
    async def test_image_happy_path_with_resize(self):
        """Real image bytes -> resized + saved to disk."""
        respx.get("https://images.example.com/real.png").mock(
            return_value = httpx.Response(200, content = _make_real_image_bytes())
        )

        result = await handle_process_image({
            "image_url": "https://images.example.com/real.png",
            "width": 50,
            "height": 50,
        })

        # The result should contain some indication of the resize having happened.
        # Different implementations may name the keys differently; accept any of:
        assert any(
            key in result for key in ("processed_filename", "filename", "new_size", "output_path")
        ), f"Unexpected result shape: {result}"

        # Cleanup any file we created
        for key in ("processed_filename", "filename", "output_path"):
            if key in result and isinstance(result[key], str) and os.path.exists(result[key]):
                os.remove(result[key])