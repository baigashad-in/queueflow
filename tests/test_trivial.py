"""
Tests for trivial endpoints and __repr__ methods.

"""
import os
import pytest
import uuid

# ════════════════════════════════════════════════════════════════════
# api/main.py — /health, /metrics, /dashboard
# ════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    async def test_health_returns_ok(self, client):
        """The health endpoint is what load balancers and uptime monitors poll.
        If it breaks, deploys fail health checks and the service appears down."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "service": "pyqueue-api"}
 
    async def test_health_does_not_require_auth(self, client):
        """Health checks must be unauthenticated — load balancers can't
        present API keys."""
        # The `client` fixture sets X-API-Key by default. Strip it.
        resp = await client.get("/health", headers={"X-API-Key": ""})
        assert resp.status_code == 200
 
 
class TestMetricsEndpoint:
    async def test_metrics_returns_prometheus_format(self, client):
        """Prometheus scrapes /metrics every 15s. If the format breaks, all
        observability disappears."""
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        # Prometheus exposition format uses text/plain with a version param
        content_type = resp.headers["content-type"]
        assert "text/plain" in content_type
        # The response body should be plain text Prometheus exposition
        body = resp.text
        assert "# HELP" in body or "# TYPE" in body, (
            "Response doesn't look like Prometheus exposition format"
        )
 
    async def test_metrics_contains_custom_queueflow_metrics(self, client):
        """At minimum, our custom metrics should be advertised in the output —
        even if their counter values are 0."""
        resp = await client.get("/metrics")
        body = resp.text
        # Counter names from core/metrics.py
        assert "queueflow_tasks_submitted_total" in body
        assert "queueflow_queue_depth" in body
 
 
class TestDashboardServing:
    """The /dashboard route serves the React SPA. It falls back to index.html
    for any path not matching a real file (so React Router can handle the URL)."""
 
    async def test_dashboard_root_returns_index(self, client, tmp_path, monkeypatch):
        """Hitting /dashboard with no path should serve index.html."""
        # Build a fake static/dashboard/index.html in tmp_path so the test
        # doesn't depend on the production frontend build
        static_dir = tmp_path / "static" / "dashboard"
        static_dir.mkdir(parents=True)
        index = static_dir / "index.html"
        index.write_text("<html>QueueFlow</html>")
 
        # Change cwd so the relative path "static/dashboard/index.html" resolves
        monkeypatch.chdir(tmp_path)
 
        resp = await client.get("/dashboard")
        assert resp.status_code == 200
        assert "QueueFlow" in resp.text
 
    async def test_dashboard_serves_existing_file_directly(self, client, tmp_path, monkeypatch):
        """If the requested path exists as a real file, serve it (not index.html)."""
        static_dir = tmp_path / "static" / "dashboard"
        static_dir.mkdir(parents=True)
        (static_dir / "index.html").write_text("<html>index</html>")
        (static_dir / "app.js").write_text("console.log('hello');")
 
        monkeypatch.chdir(tmp_path)
 
        resp = await client.get("/dashboard/app.js")
        assert resp.status_code == 200
        assert "console.log" in resp.text
 
    async def test_dashboard_unknown_path_falls_back_to_index(
        self, client, tmp_path, monkeypatch
    ):
        """Routes like /dashboard/tasks/abc should serve index.html so React
        Router can handle them client-side."""
        static_dir = tmp_path / "static" / "dashboard"
        static_dir.mkdir(parents=True)
        (static_dir / "index.html").write_text("<html>index</html>")
 
        monkeypatch.chdir(tmp_path)
 
        resp = await client.get("/dashboard/some/deep/spa/route")
        assert resp.status_code == 200
        assert "<html>index</html>" in resp.text
 
 
# ════════════════════════════════════════════════════════════════════
# core/db_models.py — __repr__ methods
# ════════════════════════════════════════════════════════════════════
 
class TestModelRepr:
    """__repr__ output appears in logs, debugger sessions, and SQLAlchemy
    error messages. If it crashes (e.g. references a removed field), every
    log line that logs an object becomes broken."""
 
    async def test_tenant_repr_includes_name_and_status(self, test_session):
        from core.db_models import Tenant
        active = Tenant(name="ActiveCorp", is_active=True)
        test_session.add(active)
        await test_session.commit()
        rep = repr(active)
        assert "ActiveCorp" in rep
        assert "active" in rep
        assert "inactive" not in rep
 
    async def test_tenant_repr_shows_inactive(self, test_session):
        from core.db_models import Tenant
        inactive = Tenant(name="OldCorp", is_active=False)
        test_session.add(inactive)
        await test_session.commit()
        rep = repr(inactive)
        assert "OldCorp" in rep
        assert "inactive" in rep
 
    async def test_apikey_repr_includes_label_and_tenant(self, test_session):
        from core.db_models import Tenant, ApiKey
        tenant = Tenant(name="ReprTestT")
        test_session.add(tenant)
        await test_session.commit()
        await test_session.refresh(tenant)
 
        key = ApiKey(tenant_id=tenant.id, key="r-key", label="primary")
        test_session.add(key)
        await test_session.commit()
 
        rep = repr(key)
        assert "primary" in rep
        assert str(tenant.id) in rep
 
    async def test_task_record_repr_includes_id_name_status(self, test_session):
        from core.db_models import Tenant, TaskRecord
        from core.models import TaskStatus
 
        tenant = Tenant(name="ReprTaskT")
        test_session.add(tenant)
        await test_session.commit()
        await test_session.refresh(tenant)
 
        task = TaskRecord(
            task_name="send_email",
            payload={"to": "x@example.com"},
            priority=5,
            max_retries=3,
            status=TaskStatus.QUEUED,
            tenant_id=tenant.id,
        )
        test_session.add(task)
        await test_session.commit()
        await test_session.refresh(task)
 
        rep = repr(task)
        assert str(task.id) in rep
        assert "send_email" in rep
        assert "queued" in rep.lower()
 
 
# ════════════════════════════════════════════════════════════════════
# core/models.py — TaskPriority._missing_
# ════════════════════════════════════════════════════════════════════
 
class TestTaskPriorityMissing:
    """TaskPriority._missing_ lets string values like 'high' resolve to the
    integer enum member. This matters when payloads come from JSON where
    integers might arrive as strings."""
 
    def test_priority_from_string_name_lowercase(self):
        from core.models import TaskPriority
        assert TaskPriority("high") == TaskPriority.HIGH
        assert TaskPriority("low") == TaskPriority.LOW
 
    def test_priority_from_string_name_mixed_case(self):
        from core.models import TaskPriority
        assert TaskPriority("Critical") == TaskPriority.CRITICAL
        assert TaskPriority("normal") == TaskPriority.NORMAL
 
    def test_priority_from_unknown_string_returns_none(self):
        from core.models import TaskPriority
        # Unknown name → ValueError from Enum lookup (None makes Enum raise)
        with pytest.raises(ValueError):
            TaskPriority("urgent")
 
    def test_priority_from_non_string_non_int_returns_none(self):
        """A None or other unhashable type should also fail cleanly."""
        from core.models import TaskPriority
        with pytest.raises(ValueError):
            TaskPriority(None)
 
    def test_priority_from_valid_int_works(self):
        """Sanity check that the standard int lookup still works."""
        from core.models import TaskPriority
        assert TaskPriority(10) == TaskPriority.HIGH
        assert TaskPriority(1) == TaskPriority.LOW