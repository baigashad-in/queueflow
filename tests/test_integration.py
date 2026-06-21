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

"""
WebSocket integration tests for /ws/tasks.

Tests cookie-based auth, connection lifecycle, and tenant-scoped event
filtering. The `ws_test_client` fixture uses real DB-backed auth: tests
seed tenant/api_key rows via `test_session_sync` and connect with a
cookie matching the seeded api_key. TestClient runs the production
lifespan in its own thread, which builds an engine in that thread's
event loop pointing at the same test database.
"""
import asyncio
import uuid
import pytest
from unittest.mock import patch
from starlette.websockets import WebSocketDisconnect


def _make_event_generator(events):
    """Build an async generator function that yields the given events."""
    async def _gen():
        for event in events:
            yield event
            await asyncio.sleep(0.01)
    return _gen


class TestWebSocketIntegration:
    """End-to-end tests for the /ws/tasks WebSocket route."""

    def test_websocket_rejects_connection_without_cookie(self, ws_test_client):
        """No qf_session cookie → server closes the connection with code 4001."""
        with pytest.raises(WebSocketDisconnect) as exc:
            with ws_test_client.websocket_connect("/ws/tasks") as ws:
                ws.receive_text()
        assert exc.value.code == 4001

    def test_websocket_rejects_invalid_cookie(self, ws_test_client):
        """Cookie set but doesn't match any registered session → 4001."""
        ws_test_client.cookies.set("qf_session", "not-a-real-key")
        with pytest.raises(WebSocketDisconnect) as exc:
            with ws_test_client.websocket_connect("/ws/tasks") as ws:
                ws.receive_text()
        assert exc.value.code == 4001

    def test_websocket_rejects_inactive_tenant(self, ws_test_client, test_session_sync):
        """Valid api_key but the tenant.is inactive = False → 4001."""
        from core.db_models import Tenant, ApiKey

        tenant = Tenant(name = f"Inactive-{uuid.uuid4().hex[:8]}", is_active=False)
        test_session_sync.add(tenant)
        test_session_sync.commit()
        test_session_sync.refresh(tenant)

        api_key = ApiKey(tenant_id = tenant.id, key = "inactive-key", is_active = True)
        test_session_sync.add(api_key)
        test_session_sync.commit()


        ws_test_client.cookies.set("qf_session", "inactive-key")
        with pytest.raises(WebSocketDisconnect) as exc:
            with ws_test_client.websocket_connect("/ws/tasks") as ws:
                ws.receive_text()
        assert exc.value.code == 4001

    def test_websocket_accepts_valid_cookie_and_forwards_event(self, ws_test_client, test_session_sync):
        """Authenticated client receives events tagged with its tenant_id."""
        from core.db_models import Tenant, ApiKey

        tenant = Tenant(name = f"Valid-{uuid.uuid4().hex[:8]}", is_active = True)
        test_session_sync.add(tenant)
        test_session_sync.commit()
        test_session_sync.refresh(tenant)

        api_key = ApiKey(tenant_id = tenant.id, key = "valid-key", is_active = True)
        test_session_sync.add(api_key)
        test_session_sync.commit()

        tenant_id_str = str(tenant.id)

        events = [{
            "task_id": "task-1",
            "task_name": "send_email",
            "status": "completed",
            "tenant_id": tenant_id_str,
            "priority": 5,
        }]

        import api.routes.ws as ws_module
        with patch.object(ws_module, "subscribe_to_events", _make_event_generator(events)):
            ws_test_client.cookies.set("qf_session", "valid-key")
            with ws_test_client.websocket_connect("/ws/tasks") as ws:
                received = ws.receive_json()
                assert received["task_id"] == "task-1"
                assert received["tenant_id"] == tenant_id_str

    def test_websocket_filters_events_from_other_tenants(self, ws_test_client, test_session_sync):
        """Security-critical: events for a different tenant must NOT be forwarded.

        Tenant A connects; the event stream contains one event for tenant B
        (must be filtered out) followed by one for A (must arrive).
        """
        from core.db_models import Tenant, ApiKey

        tenant_a = Tenant(name=f"TenantA-{uuid.uuid4().hex[:8]}", is_active=True)
        test_session_sync.add(tenant_a)
        test_session_sync.commit()
        test_session_sync.refresh(tenant_a)

        api_key = ApiKey(tenant_id = tenant_a.id, key="key-a", is_active=True)
        test_session_sync.add(api_key)
        test_session_sync.commit()

        a_id_str = str(tenant_a.id)
        b_id_str = str(uuid.uuid4())  # Random UUID for tenant B (tenant B doesn't need a DB row)

        events = [
            {"task_id": "for-b", "task_name": "x", "status": "completed",
             "tenant_id": b_id_str, "priority": 5},
            {"task_id": "for-a", "task_name": "y", "status": "completed",
             "tenant_id": a_id_str, "priority": 5},
        ]

        import api.routes.ws as ws_module
        with patch.object(ws_module, "subscribe_to_events", _make_event_generator(events)):
            ws_test_client.cookies.set("qf_session", "key-a")
            with ws_test_client.websocket_connect("/ws/tasks") as ws:
                received = ws.receive_json()
                assert received["task_id"] == "for-a"
                assert received["tenant_id"] == a_id_str


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

        # Patch the loop's get_worker_session to use our test session
        async def override_get_worker_session():
            yield test_session

        monkeypatch.setattr(sl_module, "get_worker_session", override_get_worker_session)

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

        async def override_get_worker_session():
            yield test_session

        monkeypatch.setattr(sl_module, "get_worker_session", override_get_worker_session)

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

        async def override_get_worker_session():
            yield test_session

        monkeypatch.setattr(sl_module, "get_worker_session", override_get_worker_session)

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

