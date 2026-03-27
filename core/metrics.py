from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry

# Use default registry for metrics
# REGISTRY = CollectorRegistry(auto_describe=True)

# --- Counters (always go up) ------------------------------------

tasks_submitted_total = Counter(
    "queueflow_tasks_submitted_total",
    "Total number of tasks submitted to the queue",
    ["task_name", "priority"],
)

tasks_completed_total = Counter(
    "queueflow_tasks_completed_total",
    "Total number of tasks completed successfully",
    ["task_name", "priority"],
)

tasks_failed_total = Counter(
    "queueflow_task_failed_total",
    "Total number of tasks that failed",
    ["task_name", "priority"],
)

tasks_dead_total = Counter(
    "queueflow_task_dead_total",
    "Total number of tasks marked as dead (exhausted retries)",
    ["task_name", "priority"],
)


# --- Histograms (track distributions) ------------------------------------

task_processing_seconds = Histogram(
    "queueflow_task_processing_seconds",
    "Time spent processing a task in seconds",
    ["task_name", "priority"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# --- Gauges (track current state, can go up and down) ------------------------------------

queue_depth = Gauge(
    "queueflow_queue_depth",
    "Current number of tasks waiting in each queue",
    ["queue"]
)
