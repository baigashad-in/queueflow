"""WebSocket rate limiting and concurrent-connection tracking.

Two defenses, all Redis-backed and per-API-key (keyed by prefix):

- Concurrent connection cap: SET tracks active connection IDs; new connections
  rejected once cardinality reaches the limit. Defends against resource
  exhaustion via many-simultaneous-connections.
- New-connection rate limit: counter tracks new handshakes per minute;
  requests rejected once the counter reaches the limit. Defends against
  reconnect storms (each new handshake pays the bcrypt cost).

All checks fail open on Redis errors - availability is prioritised over
strict enforcement, matching the existing HTTP rate limiter's behaviour.
Logs a warning so operators can see when Redis is degraded.
"""
import logging
import uuid

from core.config import settings
from core.queue import redis_client

logger = logging.getLogger(__name__)

# Key namespaces in Redis
_CONN_KEY_PREFIX = "ws:conn:"
_RATE_KEY_PREFIX = "ws:rate:"

# TTL for the connection SET, refreshed on activity. If a handler crashes
# without releasing the slot, the set entry expires eventually.
_CONN_TTL_SECONDS = 300
# Rate limit window - new connections are counted per minute.
_RATE_WINDOW_SECONDS = 60


async def check_rate_limit(prefix: str) -> bool:
    """Check if the caller is under the new-connection rate limit.

    Increments the per-minute counter and returns True if the caller may
    proceed, False if they've exceeded the limit. On Redis error, returns
    True (fail-open).
    """
    key = f"{_RATE_KEY_PREFIX}{prefix}"
    try:
        current = await redis_client.incr(key)
        if current == 1:
            # First increment in this window — set the TTL
            await redis_client.expire(key, _RATE_WINDOW_SECONDS)
        return current <= settings.ws_max_new_connections_per_minute
    except Exception as e:
        logger.warning(
            f"WS rate limit check failed for prefix={prefix}, allowing: {e}"
        )
        return True


async def reserve_slot(prefix: str) -> str | None:
    """Try to reserve a concurrent-connection slot for this prefix.

    Returns a connection ID string on success, None if the concurrent-cap
    was already reached. On Redis error, returns a fresh ID (fail-open).

    The connection ID must be passed to release_slot() when the connection
    ends. The Redis SET has a TTL so orphaned IDs don't leak forever.
    """
    key = f"{_CONN_KEY_PREFIX}{prefix}"
    conn_id = uuid.uuid4().hex
    try:
        current = await redis_client.scard(key)
        if current >= settings.ws_max_connections_per_key:
            return None
        await redis_client.sadd(key, conn_id)
        await redis_client.expire(key, _CONN_TTL_SECONDS)
        return conn_id
    except Exception as e:
        logger.warning(
            f"WS slot reservation failed for prefix={prefix}, allowing: {e}"
        )
        return conn_id


async def release_slot(prefix: str, conn_id: str) -> None:
    """Release a previously-reserved connection slot.

    Safe to call multiple times or on Redis errors — best-effort cleanup.
    """
    if not conn_id:
        return
    key = f"{_CONN_KEY_PREFIX}{prefix}"
    try:
        await redis_client.srem(key, conn_id)
    except Exception as e:
        logger.warning(
            f"WS slot release failed for prefix={prefix} conn={conn_id}: {e}"
        )