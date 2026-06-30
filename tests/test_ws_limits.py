"""Unit tests for core.ws_limits.

Uses fakeredis via the existing fake_redis autouse fixture so we can
exercise Redis logic without a real Redis instance, for testing purposes only.
"""
from core.ws_limits import check_rate_limit, reserve_slot, release_slot
from core.config import settings


class TestReserveSlot:
    async def test_returns_conn_id_when_under_cap(self):
        conn_id = await reserve_slot("test-prefix-1")
        assert conn_id is not None
        assert isinstance(conn_id, str)
        assert len(conn_id) == 32  # uuid4 hex

    async def test_returns_none_when_cap_reached(self):
        prefix = "test-prefix-2"
        # Fill up to the cap
        ids = []
        for _ in range(settings.ws_max_connections_per_key):
            conn_id = await reserve_slot(prefix)
            assert conn_id is not None
            ids.append(conn_id)
        # Next one should be rejected
        rejected = await reserve_slot(prefix)
        assert rejected is None

    async def test_different_prefixes_independent(self):
        # Fill prefix A to cap
        for _ in range(settings.ws_max_connections_per_key):
            await reserve_slot("prefix-A")
        # Prefix B should still have full budget
        conn_id = await reserve_slot("prefix-B")
        assert conn_id is not None


class TestReleaseSlot:
    async def test_release_frees_a_slot(self):
        prefix = "test-prefix-3"
        # Fill to cap
        ids = []
        for _ in range(settings.ws_max_connections_per_key):
            ids.append(await reserve_slot(prefix))
        # Next reservation fails
        assert await reserve_slot(prefix) is None
        # Release one
        await release_slot(prefix, ids[0])
        # Now we can reserve again
        new_id = await reserve_slot(prefix)
        assert new_id is not None

    async def test_release_with_empty_conn_id_is_noop(self):
        # Should not raise
        await release_slot("some-prefix", "")
        await release_slot("some-prefix", None)


class TestCheckRateLimit:
    async def test_under_limit_returns_true(self):
        assert await check_rate_limit("rate-prefix-1") is True

    async def test_at_limit_returns_false(self):
        prefix = "rate-prefix-2"
        # Burn through the budget
        for _ in range(settings.ws_max_new_connections_per_minute):
            assert await check_rate_limit(prefix) is True
        # Next one exceeds
        assert await check_rate_limit(prefix) is False

    async def test_different_prefixes_have_independent_budgets(self):
        prefix_a = "rate-prefix-3a"
        prefix_b = "rate-prefix-3b"
        # Burn through prefix A's budget
        for _ in range(settings.ws_max_new_connections_per_minute):
            await check_rate_limit(prefix_a)
        # A is now blocked
        assert await check_rate_limit(prefix_a) is False
        # B still has full budget
        assert await check_rate_limit(prefix_b) is True