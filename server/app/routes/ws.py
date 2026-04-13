"""WebSocket endpoints for real-time trace streaming."""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.auth import get_project_by_api_key
from app.config import settings
from app.database import SessionLocal, get_db
from app.models import Project

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])
MAX_MESSAGE_BYTES = 64 * 1024

# Maps WebSocket to (connection, project_id) for project-scoped broadcasts
active_connections: dict[WebSocket, str | None] = {}


async def broadcast_message(message: dict, project_id: str | None = None) -> None:
    """Broadcast a message to connected clients, optionally filtered by project."""
    if not active_connections:
        return

    data = json.dumps(message)
    disconnected = set()

    for connection, conn_project_id in list(active_connections.items()):
        # If project_id specified, only send to matching connections
        if project_id is not None and conn_project_id != project_id:
            continue
        try:
            await connection.send_text(data)
        except Exception:
            disconnected.add(connection)

    for conn in disconnected:
        active_connections.pop(conn, None)


def _verify_ws_api_key(api_key: str | None, db: Session | None = None) -> Project | None:
    """Verify API key for WebSocket connections (synchronous helper)."""
    if not api_key:
        return None

    if db is not None:
        try:
            return get_project_by_api_key(db, api_key)
        except Exception:
            logger.warning("WebSocket API key verification failed", exc_info=True)
            return None

    session = SessionLocal()
    try:
        return get_project_by_api_key(session, api_key)
    except Exception:
        logger.warning("WebSocket API key verification failed", exc_info=True)
        return None
    finally:
        session.close()


@router.websocket("/ws/traces")
async def traces_websocket(
    websocket: WebSocket,
    api_key: str | None = Query(None, alias="api_key"),
    db: Session = Depends(get_db),
) -> None:
    """
    WebSocket endpoint for real-time trace updates.

    Clients receive updates when new spans are ingested.
    Requires valid API key passed as query parameter.
    """
    header_api_key = websocket.headers.get("x-api-key")
    effective_api_key = header_api_key or api_key

    if api_key and not header_api_key:
        logger.info("WebSocket connected using query API key; prefer X-API-Key header")

    # Verify API key before accepting connection
    project = _verify_ws_api_key(effective_api_key, db=db)

    # Require API key unless explicit unauthenticated dev fallback is enabled.
    require_auth = (
        settings.is_production
        or settings.security_strict_mode
        or not settings.allow_unauthenticated_dev_fallback
    )
    if require_auth and project is None:
        await websocket.close(code=4001, reason="Unauthorized: Invalid or missing API key")
        return

    await websocket.accept()
    project_id = str(project.id) if project else None
    active_connections[websocket] = project_id
    logger.info(f"WebSocket connected (project={project_id}). Total connections: {len(active_connections)}")

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if len(data.encode("utf-8")) > MAX_MESSAGE_BYTES:
                    await websocket.close(code=1009, reason="Message too large")
                    break
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
    finally:
        active_connections.pop(websocket, None)
        logger.info(f"WebSocket disconnected. Total connections: {len(active_connections)}")


async def notify_span_ingested(trace_id: str, span_count: int, project_id: str | None = None) -> None:
    """Notify connected clients that new spans were ingested."""
    message = {
        "type": "span_ingested",
        "trace_id": trace_id,
        "span_count": span_count,
    }

    try:
        await broadcast_message(message, project_id=project_id)
    except Exception:
        logger.warning("Failed to broadcast span ingestion notification", exc_info=True)
