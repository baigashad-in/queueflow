import logging
import os

from contextlib import asynccontextmanager
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

import core.metrics
from core.config import settings
from core.database import build_engine, build_sessionmaker, Base

from fastapi import FastAPI
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
async def serve_dashboard(path: str = ""):
    file_path = f"static/dashboard/{path}"
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    return FileResponse("static/dashboard/index.html")


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
