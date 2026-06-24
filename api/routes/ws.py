import json
import logging
import asyncio
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from core.events import subscribe_to_events
from core.db_models import ApiKey, Tenant

router = APIRouter(prefix = "/ws", tags = ["WebSocket"])

# Origin allowlist for /ws/tasks (CSWSH guard). Mirrors CORS in api/main.py.
# Missing Origin is allowed: browsers always send it on cross-origin WS
# handshakes, so absence indicates a non-browser client (curl, Python websockets library) 
# with no cookie attack surface.

# Configurable via QUEUEFLOW_WS_ALLOWED_ORIGINS env var (comma-separated).
# Defaults below cover dev + the Azure prod deployment.
_DEFAULT_ALLOWED_ORIGINS = ",".join([
    "http://localhost:5173",
    "http://20.240.221.65:8000",
    "http://20.240.221.65",
    "https://queueflow.swedencentral.cloudapp.azure.com",
])
ALLOWED_WS_ORIGINS = {
    o.strip()
    for o in os.environ.get("QUEUEFLOW_WS_ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS).split(",")
    if o.strip()
}

logger = logging.getLogger(__name__)

async def get_tenant_from_cookie(websocket: WebSocket):
    """Extract tenant from the session cookie."""
    cookie = websocket.cookies.get("qf_session")
    if not cookie:
        return None
    
    SessionLocal = websocket.app.state.SessionLocal
    async with SessionLocal() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key == cookie, ApiKey.is_active == True)
        )
        api_key = result.scalar_one_or_none()
        if not api_key:
            return None
        
        tenant_result = await session.execute(
            select(Tenant).where(Tenant.id == api_key.tenant_id, Tenant.is_active == True)
        )
        return tenant_result.scalar_one_or_none()

# WebSocket endpoint for real-time task updates using Redis Pub/Sub (for multi-worker setups)
@router.websocket("/tasks")
async def task_feed(websocket: WebSocket):
    # CSWSH guard: reject browser handshakes from disallowed origins.
    # Missing Origin is permissive — only browsers attach cookies cross-origin,
    # and browsers always send Origin per spec, so absence reliably indicates
    # a non-browser client.
    origin = websocket.headers.get("origin")
    if origin and origin not in ALLOWED_WS_ORIGINS:
        logger.warning(f"WebSocket rejected: origin {origin!r} not in allowlist")
        await websocket.close(code=4003, reason="Origin not allowed")
        return
    
    tenant = await get_tenant_from_cookie(websocket)
    if not tenant:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept() # Accept the WebSocket connection
    tenant_id_str = str(tenant.id)
    logger.info(f"WebSocket connection established for tenant {tenant_id_str}")

    try:
        async for event in subscribe_to_events():
            # Only send events that belong to this tenant
            if str(event.get("tenant_id")) == tenant_id_str:
                try:
                    await websocket.send_json(event)
                except Exception as e:
                    logger.error(f"Websocket send failed for tenant {tenant_id_str}: {e}")
                    break
    except WebSocketDisconnect:
        logger.info(f"Websocket disconnected for tenant {tenant_id_str}")

