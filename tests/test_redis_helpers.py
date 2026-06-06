"""
Tests for the Redis-backed helper modules: lock, dlq, queue, scheduler, events,
heartbeat. Each test gets a fresh fakeredis instance via the `fake_redis` fixture
in conftest.py, so no real Redis is needed and no state leaks between tests.

"""
import asyncio
import json
import time
import pytest

from core.lock import acquire_lock, release_lock
from core.dlq import (
    push_to_dlq,
    pop_from_dlq,
    get_dlq_contents,
    get_dlq_depth,
    remove_from_dlq,
    purge_dlq,
)
from core.queue import push_task, pop_task, get_queue_depths, _get_queue_key
from core.scheduler import schedule_task, get_due_tasks, remove_scheduled
from core.events import publish, publish_task_event
from worker.heartbeat import send_heartbeat, get_active_workers
from core.constants import (
    LOCK_PREFIX,
    DLQ_KEY,
    QUEUE_CRITICAL,
    QUEUE_HIGH,
    QUEUE_NORMAL,
    QUEUE_LOW,
    SCHEDULED_KEY,
    HEARTBEAT_PREFIX,
)


# ────────────────────────────────────────────────────────────────────
# core/lock.py
# ────────────────────────────────────────────────────────────────────

class TestLock:
    """The distributed lock prevents two workers processing the same task."""

    async def test_acquire_lock_succeeds_on_first_call(self, fake_redis):
        acquired = await acquire_lock("task-1")
        assert acquired is True
        # Verify the key was actually set in Redis with a TTL
        value = await fake_redis.get(f"{LOCK_PREFIX}task-1")
        assert value == "locked"
        ttl = await fake_redis.ttl(f"{LOCK_PREFIX}task-1")
        assert 0 < ttl <= 30  # Default timeout is 30s

    async def test_acquire_lock_fails_when_already_held(self, fake_redis):
        """Second call returns False (NX semantics)."""
        first = await acquire_lock("task-1")
        second = await acquire_lock("task-1")
        assert first is True
        assert second is False

    async def test_release_lock_allows_reacquisition(self, fake_redis):
        await acquire_lock("task-1")
        await release_lock("task-1")
        # After release the key is gone and we can acquire again
        assert await fake_redis.get(f"{LOCK_PREFIX}task-1") is None
        acquired_again = await acquire_lock("task-1")
        assert acquired_again is True

    async def test_acquire_lock_custom_timeout(self, fake_redis):
        await acquire_lock("task-2", timeout=120)
        ttl = await fake_redis.ttl(f"{LOCK_PREFIX}task-2")
        assert 60 < ttl <= 120

    async def test_release_nonexistent_lock_is_safe(self, fake_redis):
        # Should not raise — release is idempotent
        await release_lock("never-locked")


# ────────────────────────────────────────────────────────────────────
# core/dlq.py
# ────────────────────────────────────────────────────────────────────

class TestDLQ:
    """The dead letter queue holds tasks that exhausted retries."""

    async def test_push_and_pop_is_fifo(self, fake_redis):
        await push_to_dlq("task-1")
        await push_to_dlq("task-2")
        await push_to_dlq("task-3")
        # lpush + rpop = FIFO. Oldest task comes out first.
        assert await pop_from_dlq() == "task-1"
        assert await pop_from_dlq() == "task-2"
        assert await pop_from_dlq() == "task-3"
        assert await pop_from_dlq() is None

    async def test_get_dlq_contents_returns_all_ids(self, fake_redis):
        await push_to_dlq("task-a")
        await push_to_dlq("task-b")
        contents = await get_dlq_contents()
        assert sorted(contents) == ["task-a", "task-b"]

    async def test_get_dlq_depth(self, fake_redis):
        assert await get_dlq_depth() == 0
        await push_to_dlq("x")
        await push_to_dlq("y")
        assert await get_dlq_depth() == 2

    async def test_remove_specific_task(self, fake_redis):
        await push_to_dlq("keep-1")
        await push_to_dlq("delete-me")
        await push_to_dlq("keep-2")
        await remove_from_dlq("delete-me")
        contents = await get_dlq_contents()
        assert "delete-me" not in contents
        assert "keep-1" in contents
        assert "keep-2" in contents

    async def test_purge_returns_depth_and_clears(self, fake_redis):
        await push_to_dlq("a")
        await push_to_dlq("b")
        await push_to_dlq("c")
        removed = await purge_dlq()
        assert removed == 3
        assert await get_dlq_depth() == 0


# ────────────────────────────────────────────────────────────────────
# core/queue.py
# ────────────────────────────────────────────────────────────────────

class TestQueueRouting:
    """Priority-to-queue mapping is the heart of priority scheduling."""

    @pytest.mark.parametrize("priority,expected", [
        (1, QUEUE_LOW),
        (3, QUEUE_LOW),
        (4, QUEUE_NORMAL),
        (5, QUEUE_NORMAL),
        (7, QUEUE_NORMAL),
        (8, QUEUE_HIGH),
        (10, QUEUE_HIGH),
        (14, QUEUE_HIGH),
        (15, QUEUE_CRITICAL),
        (20, QUEUE_CRITICAL),
        (100, QUEUE_CRITICAL),
    ])
    def test_priority_routing(self, priority, expected):
        # Note: synchronous, no fake_redis needed
        assert _get_queue_key(priority) == expected


class TestQueueOperations:
    async def test_push_and_pop_within_priority(self, fake_redis):
        """FIFO within a single priority level."""
        await push_task("first", 5)
        await push_task("second", 5)
        # rpop + lpush = FIFO order within a queue
        assert await pop_task() == "first"
        assert await pop_task() == "second"
        assert await pop_task() is None

    async def test_higher_priority_pops_first(self, fake_redis):
        """Critical beats high beats normal beats low."""
        await push_task("low-task", 1)
        await push_task("normal-task", 5)
        await push_task("high-task", 10)
        await push_task("critical-task", 20)
        # Order of pop should respect priority, regardless of insertion order
        assert await pop_task() == "critical-task"
        assert await pop_task() == "high-task"
        assert await pop_task() == "normal-task"
        assert await pop_task() == "low-task"

    async def test_pop_from_empty_queues(self, fake_redis):
        assert await pop_task() is None

    async def test_get_queue_depths(self, fake_redis):
        await push_task("a", 10)
        await push_task("b", 10)
        await push_task("c", 5)
        await push_task("d", 1)
        depths = await get_queue_depths()
        assert depths["high"] == 2
        assert depths["medium"] == 1
        assert depths["low"] == 1


# ────────────────────────────────────────────────────────────────────
# core/scheduler.py
# ────────────────────────────────────────────────────────────────────

class TestScheduler:
    """Delayed/retried tasks live in a Redis sorted set keyed by run-at time."""

    async def test_schedule_and_due(self, fake_redis):
        past = time.time() - 10
        future = time.time() + 60
        await schedule_task("past-task", past)
        await schedule_task("future-task", future)

        due = await get_due_tasks()
        assert "past-task" in due
        assert "future-task" not in due

    async def test_remove_scheduled(self, fake_redis):
        past = time.time() - 10
        await schedule_task("task-a", past)
        await remove_scheduled("task-a")
        due = await get_due_tasks()
        assert "task-a" not in due

    async def test_multiple_due_tasks_ordered_by_time(self, fake_redis):
        now = time.time()
        await schedule_task("task-3", now - 1)
        await schedule_task("task-1", now - 30)
        await schedule_task("task-2", now - 20)
        due = await get_due_tasks()
        # zrangebyscore returns by score ascending → oldest run-at first
        assert due == ["task-1", "task-2", "task-3"]


# ────────────────────────────────────────────────────────────────────
# core/events.py
# ────────────────────────────────────────────────────────────────────

class TestEvents:
    """Pub/sub fanout of status changes to connected WebSocket clients."""

    async def test_publish_writes_to_channel(self, fake_redis):
        """Subscribe first, then publish, then verify we receive the message."""
        pubsub = fake_redis.pubsub()
        await pubsub.subscribe("queueflow:events")

        # Drain the initial subscribe confirmation message
        await pubsub.get_message(timeout=1)

        await publish({"task_id": "abc", "status": "completed"})

        msg = await pubsub.get_message(timeout=1)
        assert msg is not None
        assert msg["type"] == "message"
        payload = json.loads(msg["data"])
        assert payload == {"task_id": "abc", "status": "completed"}

        await pubsub.unsubscribe()
        await pubsub.aclose()

    async def test_publish_task_event_shape(self, fake_redis):
        """publish_task_event should serialize the task's tenant_id, status, etc."""
        # Build a minimal stand-in for TaskRecord — only fields the event uses
        class FakeTask:
            id = "task-id-1"
            task_name = "send_email"
            status = "completed"
            priority = 5
            tenant_id = "tenant-1"

        pubsub = fake_redis.pubsub()
        await pubsub.subscribe("queueflow:events")
        await pubsub.get_message(timeout=1)  # drain subscribe ack

        await publish_task_event(FakeTask())

        msg = await pubsub.get_message(timeout=1)
        event = json.loads(msg["data"])

        assert event["task_id"] == "task-id-1"
        assert event["task_name"] == "send_email"
        assert event["status"] == "completed"
        assert event["priority"] == 5
        assert event["tenant_id"] == "tenant-1"
        assert "timestamp" in event  # ISO timestamp is present but value varies

        await pubsub.unsubscribe()
        await pubsub.aclose()

    async def test_publish_task_event_with_no_tenant(self, fake_redis):
        """tenant_id should serialize as None when the task has none."""
        class FakeTask:
            id = "task-id-2"
            task_name = "send_email"
            status = "completed"
            priority = 5
            tenant_id = None

        pubsub = fake_redis.pubsub()
        await pubsub.subscribe("queueflow:events")
        await pubsub.get_message(timeout=1)

        await publish_task_event(FakeTask())

        msg = await pubsub.get_message(timeout=1)
        event = json.loads(msg["data"])
        assert event["tenant_id"] is None

        await pubsub.unsubscribe()
        await pubsub.aclose()


# ────────────────────────────────────────────────────────────────────
# worker/heartbeat.py
# ────────────────────────────────────────────────────────────────────

class TestHeartbeat:
    """Each worker writes a heartbeat key with TTL; missing keys = dead worker."""

    async def test_send_heartbeat_sets_key_with_ttl(self, fake_redis):
        await send_heartbeat("worker-abc")
        value = await fake_redis.get(f"{HEARTBEAT_PREFIX}worker-abc")
        assert value is not None
        # Value is a unix timestamp as string
        assert float(value) > 0
        ttl = await fake_redis.ttl(f"{HEARTBEAT_PREFIX}worker-abc")
        assert 0 < ttl <= 30

    async def test_get_active_workers(self, fake_redis):
        await send_heartbeat("worker-1")
        await send_heartbeat("worker-2")
        active = await get_active_workers()
        assert sorted(active) == ["worker-1", "worker-2"]

    async def test_no_workers_returns_empty_list(self, fake_redis):
        active = await get_active_workers()
        assert active == []

    async def test_heartbeat_overwrites_previous(self, fake_redis):
        await send_heartbeat("worker-1")
        first_ts = float(await fake_redis.get(f"{HEARTBEAT_PREFIX}worker-1"))
        await asyncio.sleep(0.01)
        await send_heartbeat("worker-1")
        second_ts = float(await fake_redis.get(f"{HEARTBEAT_PREFIX}worker-1"))
        assert second_ts > first_ts