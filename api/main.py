from fastapi import FastAPI
from fastapi.responses import Response
from contextlib import asynccontextmanager
import logging
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from core.config import settings
from core.database import init_db
from api.routes.tasks import router as tasks_router
from api.routes.lifecycle import router as lifecycle_router
import core.metrics
from fastapi.staticfiles import StaticFiles
from api.routes.ws import router as ws_router
from api.routes.tenants import router as tenants_router
from api.auth import get_current_tenant


logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PyQueue API starting up...")
    logger.info(f"Environment: {settings.app_env}")

    # Create database tables on startup
    await init_db() # Initialize database tables on startup
    logger.info("Database tables ready")
    
    yield

    logger.info("PyQueue API shutting down...")

app = FastAPI(
    title="QueueFlow API",
    description="A distributed task queue system",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(tasks_router)
app.include_router(lifecycle_router)
app.include_router(ws_router)
app.include_router(tenants_router)

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
