"""WebSocket endpoints for real-time trace streaming."""

import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])

active_connections: Set[WebSocket] = set()


async def broadcast_message(message: dict) -> None:
    """Broadcast a message to all connected clients."""
    if not active_connections:
        return

    data = json.dumps(message)
    disconnected = set()

    for connection in active_connections:
        try:
            await connection.send_text(data)
        except Exception:
            disconnected.add(connection)

    for conn in disconnected:
        active_connections.discard(conn)


@router.websocket("/ws/traces")
async def traces_websocket(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time trace updates.

    Clients receive updates when new spans are ingested.
    """
    await websocket.accept()
    active_connections.add(websocket)
    logger.info(f"WebSocket connected. Total connections: {len(active_connections)}")

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
    finally:
        active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(active_connections)}")


def notify_span_ingested(trace_id: str, span_count: int) -> None:
    """Notify clients of new span ingestion (called from sync context)."""
    import asyncio

    message = {
        "type": "span_ingested",
        "trace_id": trace_id,
        "span_count": span_count,
    }

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(broadcast_message(message))
        else:
            loop.run_until_complete(broadcast_message(message))
    except RuntimeError:
        pass
