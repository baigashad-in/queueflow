# Task cancellation
CANCELLATION_MESSAGE = "Cancelled by user"

# Redis key prefixes

# Queue key constants
QUEUE_HIGH = "queueflow:queue:high"      # priority >=8
QUEUE_NORMAL = "queueflow:queue:medium"  # priority >=4 and <=7
QUEUE_LOW = "queueflow:queue:low"        # priority <=3
DLQ_KEY = "queueflow:dlq"
SCHEDULED_KEY = "queueflow:scheduled"
LOCK_PREFIX = "queueflow:lock:"
HEARTBEAT_PREFIX = "queueflow:worker:"
RATE_LIMIT_PREFIX = "queueflow:ratelimit:"
EVENTS_CHANNEL = "queueflow:events"