import uuid
from datetime import datetime
from enum import Enum

class TaskStatus(str, Enum):
    PENDING = "pending" # just created, not yet queued  
    QUEUED = "queued" #sitting in Redis queue, waiting to be picked up by a worker
    RUNNING = "running" #a worker has picked up the task and is currently executing it
    COMPLETED = "completed" #the task finished successfully
    FAILED = "failed" #the task failed to complete
    RETRYING = "retrying" #scheuled for retry
    DEAD = "dead" #exhausted all retry attempts and is now considered dead

class TaskPriority(int, Enum):
    LOW = 1
    NORMAL = 5
    HIGH = 10
    CRITICAL = 20

