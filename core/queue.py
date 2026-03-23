import redis.asyncio as aioredis
import json
import logging

from core.config import settings

logger = logging.getLogger(__name__)

# Redis client (created once, reused)
redis_client = aioredis.from_url(
    settings.redis_url,
    encoding = "utf-8",
    decode_responses = True,
)

# Queue key constants
QUEUE_HIGH = "queueflow:queue:high"      # priority >=8
QUEUE_MEDIUM = "queueflow:queue:medium"  # priority >=4 and <=7
QUEUE_LOW = "queueflow:queue:low"        # priority <=3

def _get_queue_key(priority: int) -> str:
    """Map a numeric priority to the correct Redis list key."""
    if priority >= 8:
        return QUEUE_HIGH
    elif priority >= 4:
        return QUEUE_MEDIUM
    else:
        return QUEUE_LOW