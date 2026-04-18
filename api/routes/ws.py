import json
import logging
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from core.events import subscribe_to_events
from core.database import get_session
from core.db_models import ApiKey, Tenant

router = APIRouter(prefix = "/ws", tags = ["WebSocket"])
logger = logging.getLogger(__name__)

async def get_tenant_from_cookie(websocket: WebSocket):
    """Extract tenant from the session cookie."""
    cookie = websocket.cookies.get("qf_session")
    if not cookie:
        return None
    
    async for session in get_session():
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

