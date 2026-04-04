"""Engram sidecar — FastAPI application entry point.

Starts the async HTTP + WebSocket server that the Tauri desktop shell
communicates with over localhost.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from api.clusters import router as clusters_router
from api.config_routes import router as config_router
from api.edges import router as edges_router
from api.positions import router as positions_router
from api.projects import router as projects_router
from api.scan import router as scan_router
from api.tags import project_tags_router, router as tags_router
from api.websocket import EventHub, router as websocket_router
from db.migrations.migrator import DatabaseMigrator
from scanner.orchestrator import ScanOrchestrator
from scanner.watcher import ProjectWatcher


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle.

    Startup:
        - Run database migrations (blocks startup on failure).
        - Create and start the scan orchestrator.
        - Trigger an initial full scan (non-blocking background task).
        - Start the file watcher for real-time project monitoring.

    Shutdown:
        - Stop the file watcher and cancel pending debounce timers.
        - Cancel any inflight full scan task.
        - Gracefully shut down the scan orchestrator.
    """
    migrator = DatabaseMigrator(config.DB_PATH, config.MIGRATIONS_DIR)
    if not migrator.migrate():
        raise RuntimeError("Database migration failed — refusing to start.")

    # Create the WebSocket event hub (must be available before orchestrator)
    event_hub = EventHub()
    app.state.event_hub = event_hub

    # Create and start the scan orchestrator
    orchestrator = ScanOrchestrator(event_hub=event_hub)
    app.state.orchestrator = orchestrator
    await orchestrator.start()

    # Trigger initial full scan (runs in background, non-blocking)
    scan_task = asyncio.create_task(orchestrator.trigger_full_scan())

    # Start file watcher for real-time project monitoring
    watcher = ProjectWatcher(orchestrator, event_hub=event_hub)
    app.state.watcher = watcher
    await watcher.start()

    yield

    # Stop watcher before tearing down the orchestrator
    await watcher.stop()

    # Cancel inflight full scan if still running, then shut down workers
    if not scan_task.done():
        scan_task.cancel()
        try:
            await scan_task
        except asyncio.CancelledError:
            pass
    await orchestrator.shutdown()


app = FastAPI(title=config.APP_TITLE, version=config.SIDECAR_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clusters_router)
app.include_router(config_router)
app.include_router(edges_router)
app.include_router(positions_router)
app.include_router(projects_router)
app.include_router(scan_router)
app.include_router(project_tags_router)
app.include_router(tags_router)
app.include_router(websocket_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Return the sidecar health status and version.

    Returns:
        A dictionary with ``status`` and ``version`` keys, confirming the
        sidecar is running and reporting its current version string.
    """
    return {"status": "ok", "version": config.SIDECAR_VERSION}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=config.APP_TITLE)
    parser.add_argument("--port", type=int, default=config.SIDECAR_PORT)
    args = parser.parse_args()
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=args.port,
        log_level="info",
    )
