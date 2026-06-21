"""
Targeted tests for the remaining coverage gaps.

Covers:
- Cancel happy path (200 OK from QUEUED status)
- subscribe_to_events generator (core/events.py)
- Redis-error swallowing in heartbeat helpers
- The default-sleep branch of heartbeat_loop (no shutdown_event)
- task_repo.get_by_id invalid-UUID short-circuit
- task_repo.get_by_tenant status filter

"""
import asyncio
import uuid
import pytest

from httpx import AsyncClient, ASGITransport

from api.main import app
from core.db_models import ApiKey, Tenant, TaskRecord
from core.models import TaskStatus
from core.constants import HEARTBEAT_PREFIX


# ────────────────────────────────────────────────────────────────────
# Helpers (mirroring _make_tenant / _make_task from test_routes_extra.py)
# ────────────────────────────────────────────────────────────────────

async def _make_tenant(session, name=None, is_active=True, key=None):
    tenant = Tenant(name=name or f"T-{uuid.uuid4().hex[:8]}", is_active=is_active)
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)

    api_key = ApiKey(
        tenant_id=tenant.id,
        key=key or f"key-{uuid.uuid4().hex[:16]}",
        is_active=True,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    return tenant, api_key.key


def _build_client(session, api_key):

    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    )


async def _make_task(session, tenant_id, status=TaskStatus.QUEUED):
    task = TaskRecord(
        task_name="send_email",
        payload={"to": "x@example.com"},
        priority=5,
        max_retries=3,
        retry_count=0,
        status=status,
        tenant_id=tenant_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


# ────────────────────────────────────────────────────────────────────
# lifecycle.py — cancel happy path
# ────────────────────────────────────────────────────────────────────

class TestCancelHappyPath:
    async def test_cancel_queued_task_succeeds(self, fake_redis, test_session):
        """Cancelling a QUEUED task: 200 OK, status moves out of cancellable_statuses."""
        tenant, key = await _make_tenant(test_session)
        task = await _make_task(test_session, tenant.id, status=TaskStatus.QUEUED)

        async with _build_client(test_session, key) as client:
            resp = await client.post(f"/tasks/{task.id}/cancel")

        assert resp.status_code == 200
        # Task should no longer be in a cancellable state
        await test_session.refresh(task)
        assert task.status not in (TaskStatus.PENDING, TaskStatus.QUEUED)
        app.dependency_overrides.clear()

    async def test_cancel_pending_task_succeeds(self, fake_redis, test_session):
        """Cancelling a PENDING (delayed) task should also succeed."""
        tenant, key = await _make_tenant(test_session)
        task = await _make_task(test_session, tenant.id, status=TaskStatus.PENDING)

        async with _build_client(test_session, key) as client:
            resp = await client.post(f"/tasks/{task.id}/cancel")

        assert resp.status_code == 200
        await test_session.refresh(task)
        assert task.status not in (TaskStatus.PENDING, TaskStatus.QUEUED)
        app.dependency_overrides.clear()


# ────────────────────────────────────────────────────────────────────
# repositories/task_repo.py — edge cases
# ────────────────────────────────────────────────────────────────────

class TestTaskRepoEdgeCases:
    async def test_get_by_id_invalid_uuid_returns_none(self, test_session):
        """Non-UUID input → return None without raising."""
        from repositories.task_repo import get_by_id
        result = await get_by_id(test_session, "not-a-uuid")
        assert result is None

    async def test_get_by_id_well_formed_but_nonexistent_returns_none(self, test_session):
        """Valid UUID format but no matching row → None."""
        from repositories.task_repo import get_by_id
        result = await get_by_id(test_session, str(uuid.uuid4()))
        assert result is None

    async def test_get_by_tenant_with_status_filter(self, test_session):
        """Status filter narrows the result set."""
        from repositories.task_repo import get_by_tenant
        tenant, _ = await _make_tenant(test_session)
        await _make_task(test_session, tenant.id, status=TaskStatus.COMPLETED)
        await _make_task(test_session, tenant.id, status=TaskStatus.COMPLETED)
        await _make_task(test_session, tenant.id, status=TaskStatus.QUEUED)

        tasks, total = await get_by_tenant(test_session, tenant.id, status="completed")
        assert total == 2
        assert len(tasks) == 2
        for t in tasks:
            assert t.status == TaskStatus.COMPLETED

    async def test_get_by_ids_returns_matching_tasks(self, test_session):
        """get_by_ids with a list of UUIDs returns matching TaskRecords."""
        from repositories.task_repo import get_by_ids
        tenant, _ = await _make_tenant(test_session)
        task1 = await _make_task(test_session, tenant.id)
        task2 = await _make_task(test_session, tenant.id)
        task3 = await _make_task(test_session, tenant.id)

        result = await get_by_ids(test_session, [task1.id, task2.id])
        assert len(result) == 2
        result_ids = {t.id for t in result}
        assert task1.id in result_ids
        assert task2.id in result_ids
        assert task3.id not in result_ids


# ────────────────────────────────────────────────────────────────────
# worker/heartbeat.py — Redis error paths + default sleep branch
# ────────────────────────────────────────────────────────────────────

class TestHeartbeatErrorPaths:
    async def test_send_heartbeat_swallows_redis_error(self, fake_redis):
        """If Redis errors during setex, send_heartbeat logs but does not raise."""
        from worker.heartbeat import send_heartbeat

        async def broken_setex(*args, **kwargs):
            raise RuntimeError("Redis is down")

        fake_redis.setex = broken_setex

        # Should complete without raising — error swallowed in except block
        await send_heartbeat("wkr-broken")

    async def test_get_active_workers_returns_empty_on_error(self, fake_redis):
        """If Redis errors during keys(), get_active_workers returns []."""
        from worker.heartbeat import get_active_workers

        async def broken_keys(*args, **kwargs):
            raise RuntimeError("Redis is down")

        fake_redis.keys = broken_keys

        result = await get_active_workers()
        assert result == []

    async def test_heartbeat_loop_default_uses_sleep(self, fake_redis):
        """Without shutdown_event, the loop uses asyncio.sleep — the production path."""
        from worker.heartbeat import heartbeat_loop

        loop_task = asyncio.create_task(
            heartbeat_loop("wkr-sleeper", interval=0.1)
        )

        # Let one iteration complete
        await asyncio.sleep(0.15)

        # Heartbeat key should exist
        value = await fake_redis.get(f"{HEARTBEAT_PREFIX}wkr-sleeper")
        assert value is not None

        # Cleanup — since there's no shutdown_event, we have to cancel
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass


# ────────────────────────────────────────────────────────────────────
# core/events.py — subscribe_to_events generator
# ────────────────────────────────────────────────────────────────────

class TestSubscribeToEvents:
    async def test_subscribe_yields_published_event(self, fake_redis):
        """A published event should be received by an active subscriber."""
        from core.events import subscribe_to_events, publish

        # Start the subscriber as a background task that collects ONE event
        async def collect_one():
            async for event in subscribe_to_events():
                return event

        collector = asyncio.create_task(collect_one())

        # Give the subscriber a moment to subscribe before we publish.
        # If we publish before subscribe() completes, the event is dropped
        # (Pub/Sub is fire-and-forget, no replay).
        await asyncio.sleep(0.1)

        # Publish an event
        await publish({"task_id": "evt-1", "status": "completed"})

        # The collector should receive it within a short timeout
        try:
            event = await asyncio.wait_for(collector, timeout=2.0)
            assert event["task_id"] == "evt-1"
            assert event["status"] == "completed"
        finally:
            if not collector.done():
                collector.cancel()
                try:
                    await collector
                except asyncio.CancelledError:
                    pass