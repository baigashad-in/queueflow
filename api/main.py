import logging
import os
import pathlib

from contextlib import asynccontextmanager
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

import core.metrics
from core.config import settings
from core.database import build_engine, build_sessionmaker, Base

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from api.routes.tasks import router as tasks_router
from api.routes.lifecycle import router as lifecycle_router
from api.routes.ws import router as ws_router
from api.routes.tenants import router as tenants_router
from api.routes.auth_routes import router as auth_router
from api.routes.admin_routes import router as admin_router
from api.auth import get_current_tenant
from api.middleware import RequestIDMiddleware, RateLimitMiddleware


logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DASHBOARD_DIR = pathlib.Path("static/dashboard").resolve()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PyQueue API starting up...")
    logger.info(f"Environment: {settings.app_env}")

    # Create an async engine bound to the current event loop and attach it
    # to app.state. This makes the engine scoped to the FastAPI lifespan
    # rather than being a module-level singleton — necessary for safe use
    # across thread boundaries (e.g. starlette TestClient).
    app.state.engine = build_engine()
    app.state.SessionLocal = build_sessionmaker(app.state.engine)

    # Skip database init during tests — the test engine fixture handles
    # table creation, and re-running init_db() under TestClient's event
    # loop causes asyncpg cross-loop errors.
    if settings.app_env != "testing":
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables ready")
    else:
        logger.info("Skipping init_db() — running under tests")
    
    yield

    logger.info("PyQueue API shutting down...")

app = FastAPI(
    title="QueueFlow API",
    description="A distributed task queue system",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS to allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins = [
        "http://localhost:5173",
        "http://20.240.221.65:8000",
        "http://20.240.221.65",
        "https://queueflow.swedencentral.cloudapp.azure.com",
    ],
    allow_credentials = True,
    allow_methods = ["*"],
    allow_headers = ["*"],
)

# Include API routers and middleware
app.include_router(tasks_router)
app.include_router(lifecycle_router)
app.include_router(ws_router)
app.include_router(tenants_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIDMiddleware)

# Serve the React dashboard
@app.get("/dashboard/{path:path}")
@app.get("/dashboard")
async def serve_dashboard(request: Request, path: str = ""):
    """Serve the REact SPA. Paths are confined to static/dashboard;
    traversal attempts get a 403 and a warning log so threat-detection
    tooling can pick them up."""
    index_file = DASHBOARD_DIR / "index.html"

    if not path:
        return FileResponse(index_file)
    
    # Resolve the requested path with `..` segments collapsed.
    requested = (DASHBOARD_DIR / path).resolve()

    # Boundary check: the resolved path must stay inside DASHBOARD_DIR.

    if not requested.is_relative_to(DASHBOARD_DIR):
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(
            f"Path traversal attempt blocked from {client_ip}: "
            f"requested path {path!r}"
        )
        raise HTTPException(status_code = 403, detail = "Not allowed")
    
    if requested.is_file():
        return FileResponse(requested)
    
    # SPA fallback for unknown but in-bounds paths (e.g. /dashboard/tasks/123)
    return FileResponse(index_file)


# After the app is created, we can mount the static directory
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "pyqueue-api"}

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content = generate_latest(),
        media_type = CONTENT_TYPE_LATEST,
    )
