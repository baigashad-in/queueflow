from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.events import subscribe_to_events

router = APIRouter(prefix = "/ws", tags = ["WebSocket"])

# WebSocket endpoint for real-time task updates using Redis Pub/Sub (for multi-worker setups)
@router.websocket("/tasks")
async def task_feed(websocket: WebSocket):
    await websocket.accept() # Accept the WebSocket connection
    try:
        async for event in subscribe_to_events():
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass