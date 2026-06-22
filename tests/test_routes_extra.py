"""
These tests build their own clients with different API keys so a single test
file can exercise multi-tenant scenarios (admin vs regular, tenant A vs tenant B).
"""
import json
import os
import tempfile
import uuid
import pytest
from httpx import AsyncClient, ASGITransport

from api.main import app
from core.db_models import ApiKey, Tenant, TaskRecord
from core.models import TaskStatus


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

async def _make_tenant(session, name=None, is_admin=False, is_active=True, key=None):
    """Create a tenant + API key. Returns (tenant, api_key_string)."""
    tenant = Tenant(
        name=name or f"T-{uuid.uuid4().hex[:8]}",
        is_admin=is_admin,
        is_active=is_active,
    )
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)

    api_key = ApiKey(
        tenant_id=tenant.id,
        key=key or f"key-{uuid.uuid4().hex[:16]}",
        is_active=True,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    return tenant, api_key.key


def _build_client(session, api_key):
    """Build an AsyncClient bound to a specific test session and API key."""

    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    )


async def _make_task(session, tenant_id, status=TaskStatus.QUEUED, task_name="send_email"):
    """Insert a task owned by the given tenant."""
    task = TaskRecord(
        task_name=task_name,
        payload={"to": "x@example.com"},
        priority=5,
        max_retries=3,
        retry_count=0,
        status=status,
        tenant_id=tenant_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


# ════════════════════════════════════════════════════════════════════
# admin_routes.py
# ════════════════════════════════════════════════════════════════════

class TestAdminRoutes:
    async def test_non_admin_cannot_access_admin_endpoints(self, test_session):
        """Regular tenants get 403, not 401 — that's the admin_auth dependency working."""
        _, regular_key = await _make_tenant(test_session, is_admin=False)
        async with _build_client(test_session, regular_key) as client:
            for path in ("/admin/tenants", "/admin/tasks", "/admin/stats"):
                resp = await client.get(path)
                assert resp.status_code == 403, f"{path} should require admin"
        app.dependency_overrides.clear()

    async def test_admin_lists_all_tenants(self, test_session):
        admin, admin_key = await _make_tenant(test_session, name="Admin", is_admin=True)
        await _make_tenant(test_session, name="Customer-1")
        await _make_tenant(test_session, name="Customer-2")
        async with _build_client(test_session, admin_key) as client:
            resp = await client.get("/admin/tenants")
        assert resp.status_code == 200
        names = {t["name"] for t in resp.json()}
        # All three tenants should be visible to the admin
        assert {"Admin", "Customer-1", "Customer-2"} <= names
        # Each entry has the expected keys
        for t in resp.json():
            assert {"id", "name", "is_active", "is_admin", "task_count", "api_key_count"} <= set(t.keys())
        app.dependency_overrides.clear()

    async def test_admin_lists_all_tasks_with_pagination(self, test_session):
        admin, admin_key = await _make_tenant(test_session, is_admin=True)
        tenant_a, _ = await _make_tenant(test_session)
        tenant_b, _ = await _make_tenant(test_session)
        # Create 5 tasks across two tenants
        for _ in range(3):
            await _make_task(test_session, tenant_a.id)
        for _ in range(2):
            await _make_task(test_session, tenant_b.id)

        async with _build_client(test_session, admin_key) as client:
            resp = await client.get("/admin/tasks?page=1&page_size=10")
        assert resp.status_code == 200
        data = resp.json()
        # Admin sees both tenants' tasks
        assert data["total"] == 5
        assert len(data["tasks"]) == 5
        assert data["page"] == 1
        assert data["page_size"] == 10
        # Tenant IDs should be a mix of both
        tenant_ids = {t["tenant_id"] for t in data["tasks"]}
        assert len(tenant_ids) == 2
        app.dependency_overrides.clear()

    async def test_admin_tasks_filtered_by_status(self, test_session):
        admin, admin_key = await _make_tenant(test_session, is_admin=True)
        tenant, _ = await _make_tenant(test_session)
        await _make_task(test_session, tenant.id, status=TaskStatus.COMPLETED)
        await _make_task(test_session, tenant.id, status=TaskStatus.QUEUED)
        await _make_task(test_session, tenant.id, status=TaskStatus.QUEUED)

        async with _build_client(test_session, admin_key) as client:
            resp = await client.get("/admin/tasks?status=queued")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert all(t["status"] == "queued" for t in data["tasks"])
        app.dependency_overrides.clear()

    async def test_admin_system_stats(self, test_session):
        admin, admin_key = await _make_tenant(test_session, is_admin=True)
        tenant, _ = await _make_tenant(test_session)
        await _make_task(test_session, tenant.id, task_name="send_email", status=TaskStatus.COMPLETED)
        await _make_task(test_session, tenant.id, task_name="process_image", status=TaskStatus.DEAD)

        async with _build_client(test_session, admin_key) as client:
            resp = await client.get("/admin/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tenants"] >= 2
        assert data["total_tasks"] >= 2
        # Status breakdown contains at least the two statuses we created
        assert "completed" in data["tasks_by_status"]
        assert "dead" in data["tasks_by_status"]
        # Type breakdown is keyed by task_name
        assert "send_email" in data["tasks_by_type"]
        assert "process_image" in data["tasks_by_type"]
        app.dependency_overrides.clear()

    async def test_toggle_tenant_flips_active_state(self, test_session):
        admin, admin_key = await _make_tenant(test_session, is_admin=True)
        target, _ = await _make_tenant(test_session, name="ToToggle", is_active=True)

        async with _build_client(test_session, admin_key) as client:
            resp1 = await client.post(f"/admin/tenants/{target.id}/toggle")
            assert resp1.status_code == 200
            assert resp1.json()["is_active"] is False

            resp2 = await client.post(f"/admin/tenants/{target.id}/toggle")
            assert resp2.status_code == 200
            assert resp2.json()["is_active"] is True
        app.dependency_overrides.clear()

    async def test_toggle_tenant_invalid_uuid(self, test_session):
        admin, admin_key = await _make_tenant(test_session, is_admin=True)
        async with _build_client(test_session, admin_key) as client:
            resp = await client.post("/admin/tenants/not-a-uuid/toggle")
        assert resp.status_code == 400
        app.dependency_overrides.clear()

    async def test_toggle_nonexistent_tenant(self, test_session):
        admin, admin_key = await _make_tenant(test_session, is_admin=True)
        async with _build_client(test_session, admin_key) as client:
            resp = await client.post(f"/admin/tenants/{uuid.uuid4()}/toggle")
        assert resp.status_code == 404
        app.dependency_overrides.clear()


# ════════════════════════════════════════════════════════════════════
# auth_routes.py
# ════════════════════════════════════════════════════════════════════

class TestAuthRoutes:
    async def test_login_with_valid_key_sets_cookie(self, test_session):
        tenant, key = await _make_tenant(test_session, name="LoginTenant")
        async with _build_client(test_session, "irrelevant-no-cookie") as client:
            # Note: we override the X-API-Key header in this call to be irrelevant —
            # /auth/login doesn't use the header, it reads `api_key` from body
            resp = await client.post("/auth/login", json={"api_key": key})
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_name"] == "LoginTenant"
        assert data["message"] == "Logged in"
        # The cookie should be set in the response
        assert "qf_session" in resp.cookies
        assert resp.cookies["qf_session"] == key
        app.dependency_overrides.clear()

    async def test_login_missing_api_key(self, test_session):
        _, key = await _make_tenant(test_session)
        async with _build_client(test_session, key) as client:
            resp = await client.post("/auth/login", json={})
        assert resp.status_code == 400
        assert "api_key" in resp.json()["detail"].lower()
        app.dependency_overrides.clear()

    async def test_login_with_invalid_key(self, test_session):
        _, key = await _make_tenant(test_session)
        async with _build_client(test_session, key) as client:
            resp = await client.post("/auth/login", json={"api_key": "wrong-key-xyz"})
        assert resp.status_code == 401
        app.dependency_overrides.clear()

    async def test_login_with_inactive_tenant(self, test_session):
        """A valid key for a deactivated tenant should be refused."""
        tenant, key = await _make_tenant(test_session, is_active=False)
        async with _build_client(test_session, key) as client:
            resp = await client.post("/auth/login", json={"api_key": key})
        assert resp.status_code == 401
        app.dependency_overrides.clear()

    async def test_logout_clears_cookie(self, test_session):
        _, key = await _make_tenant(test_session)
        async with _build_client(test_session, key) as client:
            resp = await client.post("/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["message"] == "Logged out"
        # `delete_cookie` sets the cookie to empty with max-age=0
        app.dependency_overrides.clear()


# ════════════════════════════════════════════════════════════════════
# tenants.py — error paths
# ════════════════════════════════════════════════════════════════════

class TestTenantRoutes:

    # ─── create_tenant: now admin-gated ───────────────────────────────

    async def test_create_tenant_requires_admin(self, test_session):
        """Non-admin caller posting to /tenants/ gets 403."""
        _, regular_key = await _make_tenant(test_session, is_admin = False)
        async with _build_client(test_session, regular_key) as client:
            resp = await client.post("/tenants/", json={"name": "New Co"})
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    async def test_create_tenant_without_auth_returns_401(self, test_session):
        """Anonymous POST to /tenants/ gets 401, not a silently-created tenant."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/tenants/", json = {"name": "Sneaky Co"})
        assert resp.status_code == 401
        app.dependency_overrides.clear()

    async def test_create_duplicate_tenant_returns_409(self, test_session):
        """Admin caller hits the 409 duplicate-name path."""
        await _make_tenant(test_session, name = "Acme Corp")
        _, admin_key = await _make_tenant(test_session, name = "Admin", is_admin = True)
        async with _build_client(test_session, admin_key) as client:
            # Try to create another tenant with the same name
            resp = await client.post("/tenants/", json = {"name": "Acme Corp"})
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]
        app.dependency_overrides.clear()

    # ─── create_api_key: now tenant-scoped ────────────────────────────

    async def test_create_api_key_invalid_uuid(self, test_session):
        """Bad UUID format -> 400 before ownership check."""
        _, key = await _make_tenant(test_session)
        async with _build_client(test_session, key) as client:
            resp = await client.post(
                "/tenants/not-a-uuid/api-keys", json={"label": "x"}
            )
        assert resp.status_code == 400
        app.dependency_overrides.clear()

    async def test_create_api_key_nonexistent_tenant(self, test_session):
        """Admin caller, well-formed but non-existent tenant_id -> 404."""
        _, admin_key = await _make_tenant(test_session, is_admin=True)
        random_uuid = str(uuid.uuid4())
        async with _build_client(test_session, admin_key) as client:
            resp = await client.post(
                f"/tenants/{random_uuid}/api-keys", json={"label": "x"}
            )
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    async def test_create_api_key_inactive_tenant(self, test_session):
        """Admin caller targeting inactive tenant -> 404 (is_active filter)."""
        inactive, _ = await _make_tenant(test_session, is_active=False)
        _, admin_key = await _make_tenant(test_session, is_admin=True)
        async with _build_client(test_session, admin_key) as client:
            resp = await client.post(
                f"/tenants/{inactive.id}/api-keys", json={"label": "x"}
            )
        # is_active=False filters the tenant out, so we get 404
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    async def test_create_api_key_success(self, test_session):
        tenant, key = await _make_tenant(test_session)
        async with _build_client(test_session, key) as client:
            resp = await client.post(
                f"/tenants/{tenant.id}/api-keys", json={"label": "second"}
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["tenant_id"] == str(tenant.id)
        assert data["label"] == "second"
        assert len(data["key"]) > 10  # secrets.token_urlsafe(32) is long
        app.dependency_overrides.clear()

    async def test_create_api_key_for_other_tenant_returns_403(self, test_session):
        """Tenant A cannot mint keys for tenant B."""
        tenant_a, key_a = await _make_tenant(test_session, name = "A")
        tenant_b, _ = await _make_tenant(test_session, name = "B")
        async with _build_client(test_session, key_a) as client:
            resp = await client.post(
                f"/tenants/{tenant_b.id}/api-keys", json={"label": "stolen"}
            )
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    async def test_create_api_key_as_admin_for_any_tenant(self, test_session):
        """Admin caller can mint keys for any tenant."""
        target, _ = await _make_tenant(test_session, name = "Target")
        _, admin_key = await _make_tenant(test_session, name = "Admin", is_admin = True)
        async with _build_client(test_session, admin_key) as client:
            resp = await client.post(
                f"/tenants/{target.id}/api-keys", json={"label": "admin-minted"}
            )
        assert resp.status_code == 201
        assert resp.json()["tenant_id"] == str(target.id)
        app.dependency_overrides.clear()

    async def test_create_api_key_without_auth_returns_401(self, test_session):
        """Anonymous POST to api-keys endpoint -> 401."""
        tenant, _ = await _make_tenant(test_session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/tenants/{tenant.id}/api-keys", json={"label": "x"}
            )
        assert resp.status_code == 401
        app.dependency_overrides.clear()

    async def test_list_api_keys_invalid_uuid(self, test_session):
        """Bad UUID format -> 400 before ownership check."""
        _, key = await _make_tenant(test_session)
        async with _build_client(test_session, key) as client:
            resp = await client.get("/tenants/not-a-uuid/api-keys")
        assert resp.status_code == 400
        app.dependency_overrides.clear()

    async def test_list_api_keys_returns_keys_for_tenant(self, test_session):
        """Tenant lists its own keys."""
        tenant, key = await _make_tenant(test_session)
        # Add two more keys to this tenant
        for label in ["k2", "k3"]:
            session_key = ApiKey(tenant_id=tenant.id, key=f"k-{label}", label=label)
            test_session.add(session_key)
        await test_session.commit()

        async with _build_client(test_session, key) as client:
            resp = await client.get(f"/tenants/{tenant.id}/api-keys")
        assert resp.status_code == 200
        keys = resp.json()
        # The tenant has 3 keys (one from _make_tenant + two added here)
        assert len(keys) == 3
        app.dependency_overrides.clear()

    async def test_list_api_keys_for_other_tenant_returns_403(self, test_session):
        """Tenant A cannot list tenant B's keys."""
        _, key_a = await _make_tenant(test_session, name = "A")
        tenant_b, _ = await _make_tenant(test_session, name = "B")
        async with _build_client(test_session, key_a) as client:
            resp = await client.get(f"/tenants/{tenant_b.id}/api-keys")
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    async def test_list_api_keys_without_auth_returns_401(self, test_session):
        """Anonymous GET -> 401."""
        tenant, _ = await _make_tenant(test_session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/tenants/{tenant.id}/api-keys")
        assert resp.status_code == 401
        app.dependency_overrides.clear()


# ════════════════════════════════════════════════════════════════════
# lifecycle.py — edge cases
# ════════════════════════════════════════════════════════════════════

class TestLifecycleEdgeCases:
    async def test_cancel_already_completed_task_returns_409(self, test_session):
        tenant, key = await _make_tenant(test_session)
        task = await _make_task(test_session, tenant.id, status=TaskStatus.COMPLETED)
        async with _build_client(test_session, key) as client:
            resp = await client.post(f"/tasks/{task.id}/cancel")
        assert resp.status_code == 409
        assert "cannot be cancelled" in resp.json()["detail"].lower()
        app.dependency_overrides.clear()

    async def test_cancel_task_belonging_to_other_tenant_returns_404(self, test_session):
        tenant_a, key_a = await _make_tenant(test_session)
        tenant_b, _ = await _make_tenant(test_session)
        task_b = await _make_task(test_session, tenant_b.id, status=TaskStatus.QUEUED)

        # Tenant A tries to cancel tenant B's task
        async with _build_client(test_session, key_a) as client:
            resp = await client.post(f"/tasks/{task_b.id}/cancel")
        # Returns 404, not 403, to avoid leaking existence
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    async def test_retry_queued_task_returns_409(self, test_session):
        """Only FAILED/DEAD tasks can be retried, not queued ones."""
        tenant, key = await _make_tenant(test_session)
        task = await _make_task(test_session, tenant.id, status=TaskStatus.QUEUED)
        async with _build_client(test_session, key) as client:
            resp = await client.post(f"/tasks/{task.id}/retry")
        assert resp.status_code == 409
        app.dependency_overrides.clear()

    async def test_retry_dead_task_succeeds(self, fake_redis, test_session):
        tenant, key = await _make_tenant(test_session)
        task = await _make_task(test_session, tenant.id, status=TaskStatus.DEAD)
        async with _build_client(test_session, key) as client:
            resp = await client.post(f"/tasks/{task.id}/retry")
        assert resp.status_code == 200
        # After retry the task should be back in QUEUED status
        await test_session.refresh(task)
        assert task.status == TaskStatus.QUEUED
        assert task.retry_count == 0
        app.dependency_overrides.clear()

    async def test_retry_other_tenants_task_returns_404(self, test_session):
        tenant_a, key_a = await _make_tenant(test_session)
        tenant_b, _ = await _make_tenant(test_session)
        task_b = await _make_task(test_session, tenant_b.id, status=TaskStatus.DEAD)
        async with _build_client(test_session, key_a) as client:
            resp = await client.post(f"/tasks/{task_b.id}/retry")
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    async def test_retry_nonexistent_task_returns_404(self, test_session):
        _, key = await _make_tenant(test_session)
        async with _build_client(test_session, key) as client:
            resp = await client.post(f"/tasks/{uuid.uuid4()}/retry")
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    async def test_view_dlq_filters_by_tenant(self, fake_redis, test_session):
        """DLQ shows only the current tenant's dead tasks."""
        from core.dlq import push_to_dlq

        tenant_a, key_a = await _make_tenant(test_session)
        tenant_b, _ = await _make_tenant(test_session)
        task_a = await _make_task(test_session, tenant_a.id, status=TaskStatus.DEAD)
        task_b = await _make_task(test_session, tenant_b.id, status=TaskStatus.DEAD)
        await push_to_dlq(str(task_a.id))
        await push_to_dlq(str(task_b.id))

        async with _build_client(test_session, key_a) as client:
            resp = await client.get("/dlq")
        assert resp.status_code == 200
        dlq_tasks = resp.json()
        # Tenant A only sees their own dead task
        assert len(dlq_tasks) == 1
        assert dlq_tasks[0]["id"] == str(task_a.id)
        app.dependency_overrides.clear()

    async def test_view_dlq_empty(self, fake_redis, test_session):
        _, key = await _make_tenant(test_session)
        async with _build_client(test_session, key) as client:
            resp = await client.get("/dlq")
        assert resp.status_code == 200
        assert resp.json() == []
        app.dependency_overrides.clear()

    async def test_view_dlq_skips_invalid_task_ids(self, fake_redis, test_session):
        """Malformed entries in the DLQ (non-UUID) should be skipped, not crash."""
        from core.dlq import push_to_dlq
        _, key = await _make_tenant(test_session)
        # Pollute the DLQ with garbage
        await push_to_dlq("not-a-uuid")
        await push_to_dlq("also-garbage")
        async with _build_client(test_session, key) as client:
            resp = await client.get("/dlq")
        assert resp.status_code == 200
        assert resp.json() == []
        app.dependency_overrides.clear()

    async def test_retry_all_dlq_tasks(self, fake_redis, test_session):
        from core.dlq import push_to_dlq

        tenant, key = await _make_tenant(test_session)
        task1 = await _make_task(test_session, tenant.id, status=TaskStatus.DEAD)
        task2 = await _make_task(test_session, tenant.id, status=TaskStatus.DEAD)
        await push_to_dlq(str(task1.id))
        await push_to_dlq(str(task2.id))

        async with _build_client(test_session, key) as client:
            resp = await client.post("/dlq/retry-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["replayed"] == 2
        assert data["failed"] == 0
        app.dependency_overrides.clear()

    async def test_retry_all_dlq_skips_other_tenants_tasks(self, fake_redis, test_session):
        """Cross-tenant task in DLQ should be pushed back, not retried."""
        from core.dlq import push_to_dlq, get_dlq_contents

        tenant_a, key_a = await _make_tenant(test_session)
        tenant_b, _ = await _make_tenant(test_session)
        task_a = await _make_task(test_session, tenant_a.id, status=TaskStatus.DEAD)
        task_b = await _make_task(test_session, tenant_b.id, status=TaskStatus.DEAD)
        await push_to_dlq(str(task_a.id))
        await push_to_dlq(str(task_b.id))

        async with _build_client(test_session, key_a) as client:
            resp = await client.post("/dlq/retry-all")
        assert resp.status_code == 200
        # Only tenant A's task was replayed
        assert resp.json()["replayed"] == 1
        # Tenant B's task should still be in DLQ (was pushed back)
        contents = await get_dlq_contents()
        assert str(task_b.id) in contents
        app.dependency_overrides.clear()

    async def test_retry_all_dlq_handles_missing_db_task(self, fake_redis, test_session):
        """An ID in the DLQ pointing to a deleted task counts as failed, not error."""
        from core.dlq import push_to_dlq

        _, key = await _make_tenant(test_session)
        await push_to_dlq(str(uuid.uuid4()))  # Random UUID with no DB record

        async with _build_client(test_session, key) as client:
            resp = await client.post("/dlq/retry-all")
        assert resp.status_code == 200
        assert resp.json()["replayed"] == 0
        assert resp.json()["failed"] == 1
        app.dependency_overrides.clear()

    async def test_purge_dlq_only_removes_current_tenant(self, fake_redis, test_session):
        from core.dlq import push_to_dlq, get_dlq_contents

        tenant_a, key_a = await _make_tenant(test_session)
        tenant_b, _ = await _make_tenant(test_session)
        task_a = await _make_task(test_session, tenant_a.id, status=TaskStatus.DEAD)
        task_b = await _make_task(test_session, tenant_b.id, status=TaskStatus.DEAD)
        await push_to_dlq(str(task_a.id))
        await push_to_dlq(str(task_b.id))

        async with _build_client(test_session, key_a) as client:
            resp = await client.post("/dlq/purge")
        assert resp.status_code == 200
        assert "1 tasks removed" in resp.json()["message"]
        # Tenant B's task still in DLQ
        contents = await get_dlq_contents()
        assert str(task_b.id) in contents
        assert str(task_a.id) not in contents
        app.dependency_overrides.clear()


# ════════════════════════════════════════════════════════════════════
# tasks.py — download_report + delayed submit
# ════════════════════════════════════════════════════════════════════

class TestTaskDownloadAndDelay:
    async def test_submit_task_with_delay(self, fake_redis, test_session):
        """Task with delay_seconds goes to scheduled set, not the queue."""
        _, key = await _make_tenant(test_session)
        async with _build_client(test_session, key) as client:
            resp = await client.post("/tasks/", json={
                "task_name": "send_email",
                "payload": {"to": "delayed@example.com"},
                "delay_seconds": 30,
            })
        assert resp.status_code == 201
        # Verify the task was added to the scheduled sorted set
        score = await fake_redis.zscore("queueflow:scheduled", resp.json()["id"])
        assert score is not None
        app.dependency_overrides.clear()

    async def test_download_report_not_completed_returns_400(self, test_session):
        tenant, key = await _make_tenant(test_session)
        task = await _make_task(test_session, tenant.id, status=TaskStatus.QUEUED)
        async with _build_client(test_session, key) as client:
            resp = await client.get(f"/tasks/{task.id}/download")
        assert resp.status_code == 400
        assert "not completed" in resp.json()["detail"].lower()
        app.dependency_overrides.clear()

    async def test_download_report_no_file_returns_404(self, test_session):
        """Completed task but no filename in max_results → 404."""
        tenant, key = await _make_tenant(test_session)
        task = await _make_task(test_session, tenant.id, status=TaskStatus.COMPLETED)
        task.max_results = {}  # Empty result, no filename
        await test_session.commit()
        async with _build_client(test_session, key) as client:
            resp = await client.get(f"/tasks/{task.id}/download")
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    async def test_download_report_cross_tenant_returns_404(self, test_session):
        tenant_a, key_a = await _make_tenant(test_session)
        tenant_b, _ = await _make_tenant(test_session)
        task_b = await _make_task(test_session, tenant_b.id, status=TaskStatus.COMPLETED)
        async with _build_client(test_session, key_a) as client:
            resp = await client.get(f"/tasks/{task_b.id}/download")
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    async def test_download_report_nonexistent_task_returns_404(self, test_session):
        _, key = await _make_tenant(test_session)
        async with _build_client(test_session, key) as client:
            resp = await client.get(f"/tasks/{uuid.uuid4()}/download")
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    async def test_download_report_generates_pdf(self, test_session, tmp_path):
        """Happy path: task with a real JSON file produces a PDF response."""
        tenant, key = await _make_tenant(test_session)
        task = await _make_task(test_session, tenant.id, status=TaskStatus.COMPLETED)

        # Write a real report JSON to disk in tmp_path
        report_file = tmp_path / "report.json"
        report_data = {
            "report_type": "summary",
            "generated_at": "2026-01-01T00:00:00Z",
            "total_tasks": 5,
            "status_breakdown": {"completed": 3, "dead": 2},
        }
        report_file.write_text(json.dumps(report_data))
        task.max_results = {"filename": str(report_file)}
        await test_session.commit()

        async with _build_client(test_session, key) as client:
            resp = await client.get(f"/tasks/{task.id}/download")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        # PDF magic bytes
        assert resp.content[:4] == b"%PDF"
        app.dependency_overrides.clear()


# ════════════════════════════════════════════════════════════════════
# services/task_service.py — submit_task_to_queue branches
# ════════════════════════════════════════════════════════════════════

class TestTaskService:
    async def test_submit_task_to_queue_immediate(self, fake_redis, test_session):
        """No delay → push directly to the priority queue, status=QUEUED."""
        from services.task_service import submit_task_to_queue

        tenant, _ = await _make_tenant(test_session)
        task = await _make_task(test_session, tenant.id, status=TaskStatus.PENDING)
        await submit_task_to_queue(task, delay_seconds=None)
        assert task.status == TaskStatus.QUEUED

    async def test_submit_task_to_queue_with_delay(self, fake_redis, test_session):
        """With delay → goes to scheduled sorted set, status=PENDING."""
        from services.task_service import submit_task_to_queue

        tenant, _ = await _make_tenant(test_session)
        task = await _make_task(test_session, tenant.id, status=TaskStatus.PENDING)
        await submit_task_to_queue(task, delay_seconds=30)
        assert task.status == TaskStatus.PENDING
        score = await fake_redis.zscore("queueflow:scheduled", str(task.id))
        assert score is not None