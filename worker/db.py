"""
Database engine and session factory for the worker process.

Owns a single async SQLAlchemy engine and sessionmaker for the worker
process. Engine is created once via init_worker_db() at startup and released via dispose_worker_db() at shutdown. get_worker_session() is
an async generator that yields a fresh AsyncSession per call, bound
to the worker's engine and closed automatically when the consumer
finishes iterating.

The engine is built form build_engine() in core/databse.py, so it inherits the same connection URL and pool configuration as the API,
but the engine instance and its connection pool are independent.

Intended caller: the worker process only. The API uses a separate,
lifeespan-scoped engine attached to app.state and exposes
get_api_session(request) for its routes; the two ppaths should not be mixed.
"""

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import build_engine, build_sessionmaker

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None

def init_worker_db() -> None:
    """Create the worker's engine and sessionmaker. Call once at startup."""
    global _engine, _SessionLocal
    if _engine is not None:
        logger.warning("Worker DB already initialized; ignoring re-init")
        return
    _engine = build_engine()
    _SessionLocal = build_sessionmaker(_engine)
    logger.info("Worker DB initialized")


async def get_worker_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh AsyncSession bound to the worker's engine.
    
    Use as `async for sessiion in get_worker_session(): ...` to match
    the call hsape the worker code already uses.
    """
    if _SessionLocal is None:
        raise RuntimeError(
            "Worker DB not intialized. Call inti_worker_db() at startup."
        )
    async with _SessionLocal() as session:
        yield session

async def dispose_worker_db() -> None:
    """Dispose the worker's engine. Call once at shutdown."""
    global _engine, _SessionLocal
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _SessionLocal = None
        logger.info("Worker DB disposed")

