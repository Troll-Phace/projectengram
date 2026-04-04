"""WebSocket event hub for real-time event broadcasting.

Provides an ``EventHub`` connection manager that tracks active WebSocket
clients and broadcasts structured JSON events to all of them, plus a
FastAPI WebSocket endpoint at ``/api/ws`` that the Tauri frontend
connects to for live updates (scan progress, project changes, etc.).

Event protocol (server -> client)::

    { "event": "new_project_detected", "data": { "path": "...", "name": "..." } }
    { "event": "project_updated",      "data": { "id": "...", "fields": [...] } }
    { "event": "scan_progress",        "data": { "phase": "...", "current": N, "total": N } }
    { "event": "scan_completed",       "data": { "duration_ms": N, "projects_scanned": N } }
    { "event": "project_missing",      "data": { "id": "...", "path": "..." } }
"""

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# EventHub — connection manager
# ---------------------------------------------------------------------------


class EventHub:
    """Manages WebSocket connections and broadcasts events to all clients."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a WebSocket connection and add it to the active set.

        Args:
            websocket: The incoming WebSocket connection to accept.
        """
        await websocket.accept()
        self.active_connections.append(websocket)
        _log.debug(
            "WebSocket connected — %d active connection(s)",
            len(self.active_connections),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from tracking.

        Safe to call even if the connection has already been removed.

        Args:
            websocket: The WebSocket connection to remove.
        """
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass
        _log.debug(
            "WebSocket disconnected — %d active connection(s)",
            len(self.active_connections),
        )

    async def broadcast(self, event: str, data: dict[str, Any]) -> None:
        """Send a JSON event to every connected client.

        Iterates over a snapshot of the connections list to avoid mutation
        during iteration.  Dead connections that fail to receive are
        silently removed.

        Args:
            event: Event type string (e.g. ``"scan_progress"``,
                ``"project_updated"``).
            data: Event payload dictionary.
        """
        message: dict[str, Any] = {"event": event, "data": data}
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                _log.debug("Removing dead WebSocket connection during broadcast")
                self.disconnect(connection)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()

# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time event streaming.

    Accepts the connection, enters a receive loop to keep it alive,
    and cleans up on disconnect.  The ``EventHub`` instance is retrieved
    from ``app.state.event_hub`` which is created during application
    lifespan startup.

    Args:
        websocket: The incoming WebSocket connection.
    """
    event_hub: EventHub = websocket.app.state.event_hub
    await event_hub.connect(websocket)
    try:
        while True:
            # Keep connection alive by waiting for client messages.
            # Any received text is intentionally discarded — this is a
            # server-push channel only.
            await websocket.receive_text()
    except WebSocketDisconnect:
        event_hub.disconnect(websocket)
    except Exception:
        _log.debug("WebSocket connection closed unexpectedly")
        event_hub.disconnect(websocket)
