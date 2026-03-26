from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry

# Use default registry for metrics
REGISTRY = CollectorRegistry(auto_describe=True)

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

