import json
from fastapi import WebSocket

connected_clients: set[WebSocket] = set()


async def broadcast_ticket_event(event_type: str, data: dict) -> None:
    message = json.dumps({"type": event_type, "data": data}, default=str, ensure_ascii=False)
    disconnected: list[WebSocket] = []
    for ws in connected_clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connected_clients.discard(ws)
