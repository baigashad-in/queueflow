# QueueFlow

A distributed task queue and job orchestration platform built from scratch with Python, FastAPI, Redis, and PostgreSQL

## Architecture

┌──────────────────────────────────────────────────────────────┐
│                     Client / API Layer                       │
│           FastAPI — REST + WebSocket + Auth                  │
│     Rate Limiting | Request ID Tracking | API Key Auth       │
└────────────────────────┬─────────────────────────────────────┘
                         │
        ┌────────────────┼───────────────┐
        │                │               │
   ┌────▼────────┐ ┌─────▼──────┐ ┌──────▼────────┐
   │   Redis     │ │ PostgreSQL │ │  WebSocket    │
   │  • Priority │ │ • Tasks    │ │  • Live       │
   │    Queues   │ │ • Tenants  │ │    Dashboard  │
   │  • DLQ      │ │ • API Keys │ │               │
   │  • Scheduler│ │            │ │               │
   │  • Pub/Sub  │ │            │ │               │
   └──────┬──────┘ └────────────┘ └───────────────┘
          │
   ┌──────▼───────────────────────────────────────┐
   │          Worker Pool (concurrent)            │
   │  • Semaphore-based concurrency control       │
   │  • Heartbeats (Redis TTL)                    │
   │  • Graceful shutdown (SIGTERM)               │
   │  • Scheduler loop (delayed/recurring tasks)  │
   │  • Retry logic → Dead Letter Queue           │
   └──────┬───────────────────────────────────────┘
          │
   ┌──────▼───────────────────────────────────────┐
   │           Observability                      │
   │  Prometheus metrics + Grafana dashboard      │
   └──────────────────────────────────────────────┘


## Features

01. **Priority Queues** — Three-tier Redis queues (high, medium, low) with automatic routing by priority
02. **Task Lifecycle Management** — Submit, cancel, retry tasks with full status tracking (PENDING → QUEUED → RUNNING → COMPLETED/FAILED/DEAD)
03. **Dead Letter Queue** — Failed tasks automatically moved to DLQ for inspection, replay, or purge
04. **Scheduled & Delayed Tasks** — Redis sorted sets for delayed execution and cron-style recurring tasks
05. **Concurrent Workers** — Semaphore-based concurrency control with configurable worker count
06. **Worker Heartbeats** — Redis TTL-based health detection for crash recovery
07. **Graceful Shutdown** — SIGTERM handling finishes active tasks before exiting
08. **Exponential Backoff with Jitter** — Failed tasks retry with increasing delays (2^n + random jitter) to avoid thundering herd
09. **Distributed Locking** — Redis-based locks prevent duplicate task execution across multiple workers
10. **Real-time Dashboard** — WebSocket-powered live task feed with auto-reconnect
11. **Multi-tenant Authentication** — API key auth with per-tenant task isolation
12. **Rate Limiting** — Redis sliding window rate limiting per tenant
13. **Request ID Tracking** — Unique ID on every request for debugging and tracing
14. **Observability** — Prometheus metrics (queue depth, task duration, DLQ depth) + Grafana dashboards
15. **CI Pipeline** — GitHub Actions with Postgres and Redis services, automated test suite

## Tech Stack

1. Python + FastAPI(async, modern)
2. Redis(queues, distributed locks, pub/sub for real time)
3. PostgreSQL(task metadata, audit log, scheduling)
4. Docker Compose for local dev(Redis + Postgres + workers + dashboard all wired up)
5. Prometheus + Grafana (run in Docker Compose)
6. pytest with significant test coverage including failure scenario tests

## Getting Started

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- Git

No local Python installation required — everything runs inside Docker.

## Setup

1. Clone the repository

git clone https://github.com/yourusername/queueflow.git
cd queueflow

2. Copy the example environment file

cp .env.example .env

3. Build and start all services

docker compose up --build

4. Verify everything is running

docker compose ps

You should see six containers running: api, worker, postgres, redis, prometheus, grafana.

5. Open the API docs

http://localhost:8000/docs

Click Authorize in the top right and enter your API key. Users need to create a tenant and API key first via POST /tenants/ and POST /tenants/{id}/api-keys.


### Access

| Service | URL |
|----------|----------------------------|
| API docs | http://localhost:8000/docs |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |
| Worker metrics | http://localhost:8001/metrics |

---

## API Reference

All endpoints require the `X-API-Key` header.

---

### Submit a Task

**POST** `/tasks/`

Request:
```
curl -X POST http://localhost:8000/tasks/ \
  -H "X-API-Key: dev-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "send_email",
    "payload": {
      "to": "user@example.com",
      "subject": "Welcome!"
    },
    "priority": 10,
    "max_retries": 3
  }'
```

```
Response (201 Created):
{
  "task_number": 1,
  "id": "dd4baba6-9447-4ae2-93ea-05c94051aa95",
  "task_name": "send_email",
  "payload": { "to": "user@example.com", "subject": "Welcome!" },
  "priority": 10,
  "status": "queued",
  "max_retries": 3,
  "retry_count": 0,
  "result": null,
  "error_message": null,
  "created_at": "2026-03-19T02:03:40.330989Z",
  "updated_at": "2026-03-19T02:03:40.331006Z",
  "started_at": null,
  "completed_at": null
}
```

---

### List Tasks

**GET** `/tasks/`

Optional query parameters:
- `status` — filter by status (pending, queued, running, completed, failed, retrying, dead)
- `page` — page number (default: 1)
- `page_size` — results per page (default: 20, max: 100)

Request:
```
curl http://localhost:8000/tasks/?status=completed&page=1&page_size=10 \
  -H "X-API-Key: dev-secret-key"
```

```
Response (200 OK):
{
  "tasks": [...],
  "total": 5,
  "page": 1,
  "page_size": 10
}
```

---

### Get a Task

**GET** `/tasks/{task_id}`

Request:
```
curl http://localhost:8000/tasks/dd4baba6-9447-4ae2-93ea-05c94051aa95 \
  -H "X-API-Key: dev-secret-key"
```

```
Response (200 OK):
{
  "task_number": 1,
  "id": "dd4baba6-9447-4ae2-93ea-05c94051aa95",
  "task_name": "send_email",
  "status": "completed",
  "result": {
    "sent_to": "user@example.com",
    "subject": "Welcome!",
    "status": "delivered"
  },
  "started_at": "2026-03-19T02:03:41.330989Z",
  "completed_at": "2026-03-19T02:03:41.831006Z"
}
```

---

### Error Responses

| Code | Reason |
|-----|------------------------|
| 400 | Invalid task ID format |
| 401 | Missing API key |
| 404 | Task not found (or belongs to another tenant) |
| 422 | Validation error (e.g. task_name contains spaces) |
| 429 | Rate limit exceeded (60 requests/minute) |


## Testing

Tests run inside the API container against the PostgreSQL database.

Run all tests:
docker compose exec api pytest

Run with verbose output:
docker compose exec api pytest -v

Run a specific file:
docker compose exec api pytest tests/test_api.py

The test suite covers:
- All API endpoints (submit, list, get, cancel, lifecycle, tenant)
- Authentication (missing key, wrong key)
- Validation (invalid task name, invalid UUID)
- Task handlers (dispatch, unknown handler)
- Schema validation (task names, priorities, defaults)



## What I Learned

Building Queueflow taught me how distributed systems handle work across process boundaries.
The core challenge was that Redis and PostgreSQL serve fundamentally different roles —
Redis is a fast signalling layer that tells the worker something needs doing, while
PostgreSQL is the source of truth that holds the complete task record. Getting these
two systems to stay consistent, especially across failures and retries, required thinking
carefully about the order of operations and what happens if any step fails mid-way.

Working with Python's asyncio across the API and worker processes revealed a subtle but
important constraint: metrics and state stored in memory are not shared between processes.
This forced me to run a separate metrics server on the worker and have Prometheus scrape
both processes independently. It is the kind of problem that does not appear in tutorials
but comes up immediately in real systems where multiple processes run side by side.

Implementing the priority queue using three Redis lists instead of a sorted set was a
deliberate design choice. It trades fine-grained ordering for simplicity and debuggability —
you can inspect each queue independently, reason about the drain order easily, and extend
it without touching existing logic. This kind of pragmatic decision-making, choosing the
right tool for the actual requirement rather than the most sophisticated option, is
something I developed a much stronger instinct for over the course of this project.

If I were to extend this further, I would refactor the Redis client to be
injectable so that all Redis-dependent features can be tested in the CI
pipeline, add a service layer to separate business logic from route handlers,
and implement task DAGs for defining dependencies between tasks.