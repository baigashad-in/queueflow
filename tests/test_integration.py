"""
Integration tests for the WebSocket route and scheduler loop.

These differ from the unit tests in tests/test_worker.py and tests/test_redis_helpers.py
in that they exercise the actual run loops or connection handlers, not just the
individual functions called inside them.

What's NOT covered here:
- worker/worker.py:poll_loop - signal handlers and Prometheus HTTP
  server make this fragile to test. The body is already covered via test_worker.py.
- worker/heartbeat_loop - pure async wrapper, low signal-to-noise to test.
"""
import asyncio
import json
import uuid
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.main import app
from core.database import get_session
from core.db_models import ApiKey, Tenant, TaskRecord
from core.models import TaskStatus


# ════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════

async def _make_tenant_with_key(session, key="test-ws-key"):
    """Create a tenant + an API key with a known value. Returns the tenant."""
    tenant = Tenant(name=f"WSTenant-{uuid.uuid4().hex[:8]}", is_active=True)
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)

    api_key = ApiKey(tenant_id=tenant.id, key=key, is_active=True)
    session.add(api_key)
    await session.commit()
    return tenant


def _make_event_generator(events):
    """Create an async generator that yields the given events then stops.

    Used to replace `subscribe_to_events` in the ws route — instead of reading
    from real Redis Pub/Sub, the test feeds a known sequence of events.
    """
    async def _gen():
        for event in events:
            yield event
            # Small sleep lets the event loop schedule the receive on the test side
            await asyncio.sleep(0.01)
    return _gen


# ════════════════════════════════════════════════════════════════════
# WebSocket integration tests
# ════════════════════════════════════════════════════════════════════

class TestWebSocketIntegration:
    """Tests the WebSocket route end-to-end: handshake, auth, event filtering.

    Uses Starlette's TestClient which provides a sync WebSocket client.
    We mock `subscribe_to_events` to yield a controlled event sequence so
    the tests don't depend on Redis Pub/Sub timing.
    """

    async def test_websocket_rejects_connection_without_cookie(self, test_session):
        """No cookie → close with code 4001 Unauthorized."""
        import api.routes.ws as ws_module

        # Override the route's get_session import to use our test session
        async def override_get_session():
            yield test_session

        with patch.object(ws_module, "get_session", override_get_session):
            with TestClient(app) as client:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with client.websocket_connect("/ws/tasks") as ws:
                        # Connection should be closed by the server before we can do anything
                        ws.receive_text()
                assert exc_info.value.code == 4001

    async def test_websocket_rejects_invalid_cookie(self, test_session):
        """Cookie set but doesn't match any API key → 4001."""
        import api.routes.ws as ws_module

        async def override_get_session():
            yield test_session

        with patch.object(ws_module, "get_session", override_get_session):
            with TestClient(app) as client:
                client.cookies.set("qf_session", "totally-not-a-real-key")
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with client.websocket_connect("/ws/tasks") as ws:
                        ws.receive_text()
                assert exc_info.value.code == 4001

    async def test_websocket_accepts_valid_cookie_and_forwards_event(self, test_session):
        """Valid cookie + matching tenant_id in event → event is forwarded to client."""
        import api.routes.ws as ws_module

        tenant = await _make_tenant_with_key(test_session, key="ws-key-1")
        tenant_id_str = str(tenant.id)

        async def override_get_session():
            yield test_session

        events_to_yield = [
            {"task_id": "task-1", "task_name": "send_email", "status": "completed",
             "tenant_id": tenant_id_str, "priority": 5},
        ]

        with patch.object(ws_module, "get_session", override_get_session), \
             patch.object(ws_module, "subscribe_to_events", _make_event_generator(events_to_yield)):
            with TestClient(app) as client:
                client.cookies.set("qf_session", "ws-key-1")
                with client.websocket_connect("/ws/tasks") as ws:
                    received = ws.receive_json()
                    assert received["task_id"] == "task-1"
                    assert received["tenant_id"] == tenant_id_str

    async def test_websocket_filters_events_from_other_tenants(self, test_session):
        """An event for another tenant should NOT be forwarded.

        This is the security-critical test: it verifies the tenant isolation
        on the WebSocket route. A bug here would leak task data across tenants.
        """
        import api.routes.ws as ws_module

        tenant_a = await _make_tenant_with_key(test_session, key="ws-key-a")
        tenant_b = await _make_tenant_with_key(test_session, key="ws-key-b")
        tenant_a_id = str(tenant_a.id)
        tenant_b_id = str(tenant_b.id)

        async def override_get_session():
            yield test_session

        # Send three events: one for tenant_b (should NOT arrive), then one for
        # tenant_a (SHOULD arrive), then another for tenant_b (should NOT arrive)
        events_to_yield = [
            {"task_id": "task-for-b", "task_name": "x", "status": "completed",
             "tenant_id": tenant_b_id, "priority": 5},
            {"task_id": "task-for-a", "task_name": "y", "status": "completed",
             "tenant_id": tenant_a_id, "priority": 5},
            {"task_id": "task-for-b-2", "task_name": "z", "status": "failed",
             "tenant_id": tenant_b_id, "priority": 5},
        ]

        with patch.object(ws_module, "get_session", override_get_session), \
             patch.object(ws_module, "subscribe_to_events", _make_event_generator(events_to_yield)):
            with TestClient(app) as client:
                client.cookies.set("qf_session", "ws-key-a")
                with client.websocket_connect("/ws/tasks") as ws:
                    # The only event tenant_a should see is task-for-a.
                    # If the filtering is broken, we'll receive task-for-b first instead.
                    received = ws.receive_json()
                    assert received["task_id"] == "task-for-a"
                    assert received["tenant_id"] == tenant_a_id

    async def test_websocket_rejects_inactive_tenant(self, test_session):
        """A valid key for a deactivated tenant should be rejected."""
        import api.routes.ws as ws_module

        tenant = Tenant(name=f"InactiveWS-{uuid.uuid4().hex[:8]}", is_active=False)
        test_session.add(tenant)
        await test_session.commit()
        await test_session.refresh(tenant)

        api_key = ApiKey(tenant_id=tenant.id, key="inactive-key", is_active=True)
        test_session.add(api_key)
        await test_session.commit()

        async def override_get_session():
            yield test_session

        with patch.object(ws_module, "get_session", override_get_session):
            with TestClient(app) as client:
                client.cookies.set("qf_session", "inactive-key")
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with client.websocket_connect("/ws/tasks") as ws:
                        ws.receive_text()
                assert exc_info.value.code == 4001


# ════════════════════════════════════════════════════════════════════
# scheduler_loop integration test
# ════════════════════════════════════════════════════════════════════

class TestSchedulerLoopIntegration:
    """Tests the scheduler_loop end-to-end.

    The loop is an infinite `while True` that polls Redis for due tasks
    and moves them from the scheduled set to the work queue. We run the
    loop as a background task, set up state, wait briefly, then cancel.
    """

    async def test_scheduler_moves_due_task_to_queue(self, fake_redis, test_session, monkeypatch):
        """A task scheduled for the past should be moved to the work queue."""
        import time
        import worker.scheduler_loop as sl_module
        from core.scheduler import schedule_task
        from core.constants import QUEUE_NORMAL

        # Insert a tenant and a task in the database
        tenant = Tenant(name=f"SchedTenant-{uuid.uuid4().hex[:8]}", is_active=True)
        test_session.add(tenant)
        await test_session.commit()
        await test_session.refresh(tenant)

        task = TaskRecord(
            task_name="send_email",
            payload={"to": "x@example.com"},
            priority=5,
            max_retries=3,
            status=TaskStatus.PENDING,
            tenant_id=tenant.id,
        )
        test_session.add(task)
        await test_session.commit()
        await test_session.refresh(task)

        # Schedule the task to run in the past (already due)
        await schedule_task(str(task.id), time.time() - 10)

        # Verify it's in the scheduled set before we start the loop
        score = await fake_redis.zscore("queueflow:scheduled", str(task.id))
        assert score is not None

        # Patch the loop's get_session to use our test session
        async def override_get_session():
            yield test_session

        monkeypatch.setattr(sl_module, "get_session", override_get_session)

        # Run the loop in the background. It has a sleep(5) at the bottom of
        # each iteration so it shouldn't burn CPU. Give it a moment to act.
        loop_task = asyncio.create_task(sl_module.scheduler_loop())
        try:
            # Wait up to 2 seconds for the scheduler to process the due task.
            # In practice it processes on the first iteration (instant).
            for _ in range(20):
                await asyncio.sleep(0.1)
                queued = await fake_redis.lrange(QUEUE_NORMAL, 0, -1)
                if str(task.id) in queued:
                    break
        finally:
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

        # Task should now be in the work queue, removed from scheduled set
        queued = await fake_redis.lrange(QUEUE_NORMAL, 0, -1)
        assert str(task.id) in queued
        scheduled_score = await fake_redis.zscore("queueflow:scheduled", str(task.id))
        assert scheduled_score is None

        # Task status should be QUEUED in the DB
        await test_session.refresh(task)
        assert task.status == TaskStatus.QUEUED

    async def test_scheduler_does_not_touch_future_tasks(self, fake_redis, test_session, monkeypatch):
        """A task scheduled for the future should stay in the scheduled set."""
        import time
        import worker.scheduler_loop as sl_module
        from core.scheduler import schedule_task
        from core.constants import QUEUE_NORMAL

        tenant = Tenant(name=f"SchedFutureTenant-{uuid.uuid4().hex[:8]}", is_active=True)
        test_session.add(tenant)
        await test_session.commit()
        await test_session.refresh(tenant)

        task = TaskRecord(
            task_name="send_email",
            payload={"to": "y@example.com"},
            priority=5,
            max_retries=3,
            status=TaskStatus.PENDING,
            tenant_id=tenant.id,
        )
        test_session.add(task)
        await test_session.commit()
        await test_session.refresh(task)

        # Schedule for 5 minutes in the future
        await schedule_task(str(task.id), time.time() + 300)

        async def override_get_session():
            yield test_session

        monkeypatch.setattr(sl_module, "get_session", override_get_session)

        loop_task = asyncio.create_task(sl_module.scheduler_loop())
        try:
            # Give the loop one full iteration
            await asyncio.sleep(0.5)
        finally:
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

        # Task should STILL be in the scheduled set, NOT in the work queue
        queued = await fake_redis.lrange(QUEUE_NORMAL, 0, -1)
        assert str(task.id) not in queued
        scheduled_score = await fake_redis.zscore("queueflow:scheduled", str(task.id))
        assert scheduled_score is not None

        await test_session.refresh(task)
        # Status unchanged from PENDING
        assert task.status == TaskStatus.PENDING

    async def test_scheduler_handles_orphan_task_id_gracefully(self, fake_redis, test_session, monkeypatch):
        """A task ID in the scheduled set with no matching DB record should be
        skipped without crashing the loop."""
        import time
        import worker.scheduler_loop as sl_module
        from core.scheduler import schedule_task

        # Schedule a UUID that doesn't exist in the DB
        orphan_id = str(uuid.uuid4())
        await schedule_task(orphan_id, time.time() - 10)

        async def override_get_session():
            yield test_session

        monkeypatch.setattr(sl_module, "get_session", override_get_session)

        loop_task = asyncio.create_task(sl_module.scheduler_loop())
        try:
            # Give the loop time to encounter the orphan and continue
            await asyncio.sleep(0.5)
        finally:
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

        # The orphan should have been removed from the scheduled set (the loop
        # calls remove_scheduled before checking the DB), and the loop should
        # still be alive (no crash). We verify the latter by the fact that
        # cancel() worked — if the loop had crashed it would have raised on
        # cancellation with a different exception.
        scheduled_score = await fake_redis.zscore("queueflow:scheduled", orphan_id)
        assert scheduled_score is None