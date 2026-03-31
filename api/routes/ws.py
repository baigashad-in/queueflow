from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.events import subscribe, unsubscribe

router = APIRouter(prefix = "/ws", tags = ["WebSocket"])

@router.websocket("/tasks")
async def task_feed(websocket: WebSocket):
    await websocket.accept() # Accept the WebSocket connection
    queue = subscribe()
    try:
        while True:
            event = await queue.get() # blocks until an event arrives
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe(queue)