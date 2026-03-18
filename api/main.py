from fastapi import FastAPI
from contextlib import asynccontextmanager
import logging

from core.config import settings
from core.database import init_db
from api.routes.tasks import router as tasks_router

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PyQueue API starting up...")
    logger.info(f"Environment: {settings.app_env}")

    yield

    logger.info("PyQueue API shutting down...")


app = FastAPI(
    title="PyQueue",
    description="A distributed task queue system",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(tasks_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "pyqueue-api"}
