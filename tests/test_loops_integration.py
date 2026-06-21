"""
Integration tests for worker/worker.py:poll_loop and worker/heartbeat.py:heartbeat_loop.

These exercise the loop bodies end-to-end by:
- Disabling signal handlers and the Prometheus port-binding (injected deps)
- Pushing a task to the queue
- Starting the loop as a background task
- Waiting for the task to be processed
- Setting a shutdown event and verifying the loop exits cleanly
"""
import asyncio
import uuid
import pytest

from core.db_models import Tenant, TaskRecord
from core.models import TaskStatus
from core.queue import push_task
from core.constants import HEARTBEAT_PREFIX


# ════════════════════════════════════════════════════════════════════
# poll_loop integration
# ════════════════════════════════════════════════════════════════════

class TestPollLoopIntegration:
    """End-to-end tests for the worker's main poll loop."""

    async def test_poll_loop_processes_queued_task(self, fake_redis, test_session, monkeypatch):
        """A task pushed to the queue should be picked up and run to COMPLETED."""
        import worker.worker as worker_module

        # Create a tenant and task
        tenant = Tenant(name=f"PollT-{uuid.uuid4().hex[:8]}", is_active=True)
        test_session.add(tenant)
        await test_session.commit()
        await test_session.refresh(tenant)

        task = TaskRecord(
            task_name="send_email",
            payload={"to": "x@example.com", "subject": "s", "body": "b"},
            priority=5,
            max_retries=3,
            status=TaskStatus.QUEUED,
            tenant_id=tenant.id,
        )
        test_session.add(task)
        await test_session.commit()
        await test_session.refresh(task)
        task_id_str = str(task.id)

        # Push the task ID onto the work queue
        await push_task(task_id_str, 5)

        # Patch get_worker_session in the worker module to use our test session
        async def override_get_worker_session():
            yield test_session
        monkeypatch.setattr(worker_module, "get_worker_session", override_get_worker_session)

        # Patch dispatch to a fast no-op so the task completes immediately
        async def fast_dispatch(name, payload, task_id=None):
            return {"sent_to": payload["to"], "status": "ok"}
        monkeypatch.setattr(worker_module, "dispatch", fast_dispatch)

        # Run poll_loop with injected dependencies — no signal handlers,
        # no real metrics server, controllable shutdown event
        shutdown = asyncio.Event()
        loop_task = asyncio.create_task(worker_module.poll_loop(
            metrics_server_starter=lambda: None,
            install_signal_handlers=False,
            shutdown_event=shutdown,
        ))

        try:
            # Poll the DB for status change with a timeout
            for _ in range(40):  # up to ~4 seconds
                await asyncio.sleep(0.1)
                await test_session.refresh(task)
                if task.status == TaskStatus.COMPLETED:
                    break
        finally:
            shutdown.set()
            try:
                await asyncio.wait_for(loop_task, timeout=2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                loop_task.cancel()

        assert task.status == TaskStatus.COMPLETED, (
            f"Task should be COMPLETED, got {task.status}. The poll loop "
            f"didn't pick it up — check that fake_redis is patched in worker.py."
        )

    async def test_poll_loop_exits_cleanly_on_shutdown(self, fake_redis, test_session):
        """When shutdown_event is set, the loop exits promptly even with no tasks."""
        import worker.worker as worker_module

        shutdown = asyncio.Event()
        loop_task = asyncio.create_task(worker_module.poll_loop(
            metrics_server_starter=lambda: None,
            install_signal_handlers=False,
            shutdown_event=shutdown,
        ))

        # Let the loop run one idle iteration, then signal shutdown
        await asyncio.sleep(0.1)
        shutdown.set()

        # The loop should exit promptly (wait_for with 5s timeout in the loop body)
        await asyncio.wait_for(loop_task, timeout=10)
        assert loop_task.done()

    async def test_poll_loop_handles_pop_exception(self, fake_redis, test_session, monkeypatch):
        """If pop_task raises, the loop logs and continues (doesn't crash)."""
        import worker.worker as worker_module

        call_count = {"n": 0}

        async def flaky_pop():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated Redis blip")
            return None  # subsequent calls return None to keep loop idle

        monkeypatch.setattr(worker_module, "pop_task", flaky_pop)

        shutdown = asyncio.Event()
        loop_task = asyncio.create_task(worker_module.poll_loop(
            metrics_server_starter=lambda: None,
            install_signal_handlers=False,
            shutdown_event=shutdown,
        ))

        # Give the loop time to encounter the exception and recover
        await asyncio.sleep(0.2)
        shutdown.set()
        await asyncio.wait_for(loop_task, timeout=10)

        # The loop should have called pop_task at least once despite the exception
        assert call_count["n"] >= 1


# ════════════════════════════════════════════════════════════════════
# heartbeat_loop integration
# ════════════════════════════════════════════════════════════════════

class TestHeartbeatLoopIntegration:
    async def test_heartbeat_loop_writes_periodic_keys(self, fake_redis):
        """The loop should write a heartbeat key on each iteration."""
        from worker.heartbeat import heartbeat_loop

        worker_id = "wkr-test-1"
        shutdown = asyncio.Event()

        loop_task = asyncio.create_task(
            heartbeat_loop(worker_id, interval=1, shutdown_event=shutdown)
        )

        # Wait long enough for at least one heartbeat write
        await asyncio.sleep(0.2)

        # Heartbeat key should exist
        value = await fake_redis.get(f"{HEARTBEAT_PREFIX}{worker_id}")
        assert value is not None

        shutdown.set()
        await asyncio.wait_for(loop_task, timeout=3)
        assert loop_task.done()

    async def test_heartbeat_loop_exits_on_shutdown(self, fake_redis):
        """Setting shutdown_event should cause the loop to return."""
        from worker.heartbeat import heartbeat_loop

        shutdown = asyncio.Event()
        loop_task = asyncio.create_task(
            heartbeat_loop("wkr-test-2", interval=10, shutdown_event=shutdown)
        )

        await asyncio.sleep(0.05)
        shutdown.set()
        # Should exit within the interval window — wait_for handles that
        await asyncio.wait_for(loop_task, timeout=2)
        assert loop_task.done()