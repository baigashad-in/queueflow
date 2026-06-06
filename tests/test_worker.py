"""
Tests for worker/worker.py — the core processing loop.

These cover:
- process_task happy path → COMPLETED
- process_task failure path within retry budget → RETRYING + scheduled
- process_task failure path exhausting retries → DEAD + DLQ push
- process_with_limit when lock is already held by another worker → skip
- process_with_limit when task was cancelled → skip
- fire_webhook with no callback URL → no-op
- fire_webhook with callback URL → POST sent
- fire_webhook with failing callback → caught and logged, no exception bubbles up
- update_idle_metrics → reads queue depths and DLQ depth

Coverage gain: roughly 90 of the 133 statements in worker/worker.py.
What remains uncovered: poll_loop (the infinite loop), shutdown signal handling,
and the __main__ block. Those need integration tests, not unit tests.
"""
import asyncio
import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone
import httpx

from core.db_models import TaskRecord, Tenant
from core.models import TaskStatus
from core.dlq import get_dlq_contents
from core.scheduler import get_due_tasks
from core.lock import acquire_lock
from core.constants import CANCELLATION_MESSAGE
from worker.worker import (
    process_task,
    process_with_limit,
    fire_webhook,
    update_idle_metrics,
)


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

async def _make_task(session, task_name="send_email", payload=None, max_retries=3, priority=5):
    """Insert a fresh TaskRecord and a Tenant to own it. Returns the task."""
    tenant = Tenant(name=f"WorkerTestTenant-{uuid.uuid4().hex[:8]}")
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)

    task = TaskRecord(
        task_name=task_name,
        payload=payload or {"to": "test@example.com", "subject": "test", "body": "x"},
        priority=priority,
        max_retries=max_retries,
        retry_count=0,
        status=TaskStatus.QUEUED,
        tenant_id=tenant.id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


# ────────────────────────────────────────────────────────────────────
# process_task — happy path
# ────────────────────────────────────────────────────────────────────

class TestProcessTaskHappyPath:
    async def test_completes_successfully(self, fake_redis, test_session):
        task = await _make_task(test_session, task_name="send_email")

        # Patch dispatch so we don't actually send an email
        async def fake_dispatch(name, payload, task_id=None):
            return {"sent_to": payload["to"], "status": "delivered"}

        with patch("worker.worker.dispatch", side_effect=fake_dispatch):
            await process_task(task, test_session)

        await test_session.refresh(task)
        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None
        assert task.started_at is not None
        assert task.max_results == {"sent_to": "test@example.com", "status": "delivered"}
        assert task.retry_count == 0  # No retry happened

    async def test_dispatch_called_with_task_id(self, fake_redis, test_session):
        """Handlers receive the task_id so generate_report can exclude itself."""
        task = await _make_task(test_session)

        captured = {}
        async def fake_dispatch(name, payload, task_id=None):
            captured["task_id"] = task_id
            return {"ok": True}

        with patch("worker.worker.dispatch", side_effect=fake_dispatch):
            await process_task(task, test_session)

        assert captured["task_id"] == str(task.id)


# ────────────────────────────────────────────────────────────────────
# process_task — retry path
# ────────────────────────────────────────────────────────────────────

class TestProcessTaskRetry:
    async def test_first_failure_schedules_retry(self, fake_redis, test_session):
        """retry_count <= max_retries → status=RETRYING and added to scheduled set."""
        task = await _make_task(test_session, max_retries=3)

        async def fake_dispatch(name, payload, task_id=None):
            raise ValueError("simulated failure")

        with patch("worker.worker.dispatch", side_effect=fake_dispatch):
            await process_task(task, test_session)

        await test_session.refresh(task)
        assert task.status == TaskStatus.RETRYING
        assert task.retry_count == 1
        # The task should now be in the scheduled set, due in the future
        # We can't easily check the exact scheduled time, but the task ID should be there
        # (get_due_tasks only returns tasks with score <= now, so future retries won't appear)
        # Instead check the sorted set directly
        score = await fake_redis.zscore("queueflow:scheduled", str(task.id))
        assert score is not None
        assert score > 0

    async def test_exhausting_retries_marks_dead_and_pushes_to_dlq(
        self, fake_redis, test_session
    ):
        """retry_count > max_retries → DEAD + DLQ push."""
        task = await _make_task(test_session, max_retries=2)
        # Pre-set retry_count so the next failure exhausts the budget
        task.retry_count = 2
        await test_session.commit()

        async def fake_dispatch(name, payload, task_id=None):
            raise RuntimeError("final failure")

        with patch("worker.worker.dispatch", side_effect=fake_dispatch):
            await process_task(task, test_session)

        await test_session.refresh(task)
        assert task.status == TaskStatus.DEAD
        assert task.retry_count == 3
        assert "final failure" in task.error_message

        # Verify the task was pushed to the DLQ
        dlq_contents = await get_dlq_contents()
        assert str(task.id) in dlq_contents


# ────────────────────────────────────────────────────────────────────
# process_with_limit — locking
# ────────────────────────────────────────────────────────────────────

class TestProcessWithLimit:
    async def test_skips_if_lock_already_held(self, fake_redis, test_session):
        """Second worker can't grab the lock and exits cleanly without processing."""
        task = await _make_task(test_session)

        # Simulate another worker holding the lock
        await acquire_lock(str(task.id))

        semaphore = asyncio.Semaphore(1)
        dispatch_called = []

        async def fake_dispatch(*args, **kwargs):
            dispatch_called.append(True)
            return {}

        # Patch get_session to yield our test_session (not the real DB pool)
        async def fake_get_session():
            yield test_session

        with patch("worker.worker.dispatch", side_effect=fake_dispatch), \
             patch("worker.worker.get_session", fake_get_session):
            await process_with_limit(semaphore, str(task.id))

        # Dispatch never ran because the lock acquisition failed
        assert dispatch_called == []
        # Task status untouched
        await test_session.refresh(task)
        assert task.status == TaskStatus.QUEUED

    async def test_skips_cancelled_task(self, fake_redis, test_session):
        """A task cancelled while waiting for the lock is skipped, not processed."""
        task = await _make_task(test_session)
        task.status = TaskStatus.FAILED
        task.error_message = CANCELLATION_MESSAGE
        await test_session.commit()

        semaphore = asyncio.Semaphore(1)
        dispatch_called = []

        async def fake_dispatch(*args, **kwargs):
            dispatch_called.append(True)
            return {}

        async def fake_get_session():
            yield test_session

        with patch("worker.worker.dispatch", side_effect=fake_dispatch), \
             patch("worker.worker.get_session", fake_get_session):
            await process_with_limit(semaphore, str(task.id))

        # Should have skipped due to the cancellation marker
        assert dispatch_called == []

    async def test_processes_normal_task(self, fake_redis, test_session):
        """Happy path through the full process_with_limit wrapper."""
        task = await _make_task(test_session)
        semaphore = asyncio.Semaphore(1)

        async def fake_dispatch(name, payload, task_id=None):
            return {"ok": True}

        async def fake_get_session():
            yield test_session

        with patch("worker.worker.dispatch", side_effect=fake_dispatch), \
             patch("worker.worker.get_session", fake_get_session):
            await process_with_limit(semaphore, str(task.id))

        await test_session.refresh(task)
        assert task.status == TaskStatus.COMPLETED

        # Lock should have been released (acquirable again)
        can_acquire = await acquire_lock(str(task.id))
        assert can_acquire is True

    async def test_skips_missing_task(self, fake_redis, test_session):
        """If the task ID doesn't exist in the DB, return cleanly without crashing."""
        semaphore = asyncio.Semaphore(1)
        fake_task_id = str(uuid.uuid4())

        async def fake_get_session():
            yield test_session

        with patch("worker.worker.get_session", fake_get_session):
            # Should not raise
            await process_with_limit(semaphore, fake_task_id)


# ────────────────────────────────────────────────────────────────────
# fire_webhook
# ────────────────────────────────────────────────────────────────────

class TestFireWebhook:
    async def test_no_callback_url_is_noop(self, fake_redis, test_session):
        task = await _make_task(test_session)
        task.callback_url = None
        await test_session.commit()

        # Should return without calling httpx — nothing to assert beyond "doesn't raise"
        await fire_webhook(task)

    async def test_callback_posts_to_url(self, fake_redis, test_session):
        task = await _make_task(test_session)
        task.callback_url = "https://example.com/webhook"
        task.status = TaskStatus.COMPLETED
        task.max_results = {"sent_to": "user@example.com"}
        task.completed_at = datetime.now(timezone.utc)
        await test_session.commit()

        # Mock httpx.AsyncClient.post so we don't make a real network call
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            await fire_webhook(task)

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert call_args.args[0] == "https://example.com/webhook"
            payload = call_args.kwargs["json"]
            assert payload["task_id"] == str(task.id)
            assert payload["status"] == "completed"
            assert payload["result"] == {"sent_to": "user@example.com"}

    async def test_callback_failure_swallowed(self, fake_redis, test_session):
        """A failing webhook should be logged but not propagate to the worker."""
        task = await _make_task(test_session)
        task.callback_url = "https://nonexistent.invalid/hook"
        await test_session.commit()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("cannot reach host")
            )
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Should NOT raise — exception is caught and logged
            await fire_webhook(task)


# ────────────────────────────────────────────────────────────────────
# update_idle_metrics
# ────────────────────────────────────────────────────────────────────

class TestUpdateIdleMetrics:
    async def test_returns_queue_and_dlq_depths(self, fake_redis):
        """When idle, the worker updates Prometheus gauges with current depths."""
        from core.queue import push_task
        from core.dlq import push_to_dlq

        # Seed the queues with some tasks
        await push_task("h1", 10)
        await push_task("h2", 10)
        await push_task("m1", 5)
        await push_to_dlq("dead1")
        await push_to_dlq("dead2")
        await push_to_dlq("dead3")

        depths, dlq_d = await update_idle_metrics()

        assert depths["high"] == 2
        assert depths["medium"] == 1
        assert depths["low"] == 0
        assert dlq_d == 3