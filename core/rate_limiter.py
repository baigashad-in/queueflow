from core.queue import redis_client
import logging

logger = logging.getLogger(__name__)

RATE_LIMIT_PREFIX = "queueflow:ratelimit:"
DEFAULT_RATE_LIMIT = 60 # requests per minute

async def check_rate_limit(tenant_id: str, limit: int = DEFAULT_RATE_LIMIT) -> dict:
    """Check if a tenant has exceeded their rate limit.
    Returns {"allowed": True/Flase, "remaining": int, "reset_in": int}"""
    key = f"{RATE_LIMIT_PREFIX}{tenant_id}"

    current = await redis_client.incr(key)

    if current == 1:
        await redis_client.expire(key, 60) # set expiration to 60 seconds

    ttl = await redis_client.ttl(key)
    remaining = max(0, limit -current)

    return{
        "allowed": current <= limit,
        "remaining": remaining,
        "reset_in": ttl,
    }

