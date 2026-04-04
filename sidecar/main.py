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
from db.migrations.migrator import DatabaseMigrator
from scanner.orchestrator import ScanOrchestrator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle.

    Startup:
        - Run database migrations (blocks startup on failure).
        - Create and start the scan orchestrator.
        - Trigger an initial full scan (non-blocking background task).

    Shutdown:
        - Gracefully shut down the scan orchestrator.
    """
    migrator = DatabaseMigrator(config.DB_PATH, config.MIGRATIONS_DIR)
    if not migrator.migrate():
        raise RuntimeError("Database migration failed — refusing to start.")

    # Create and start the scan orchestrator
    orchestrator = ScanOrchestrator()
    app.state.orchestrator = orchestrator
    await orchestrator.start()

    # Trigger initial full scan (runs in background, non-blocking)
    scan_task = asyncio.create_task(orchestrator.trigger_full_scan())

    # TODO: Phase 15 — start file watcher background task
    yield
    # TODO: Phase 15 — cancel file watcher task

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


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Return the sidecar health status and version.

    Returns:
        A dictionary with ``status`` and ``version`` keys, confirming the
        sidecar is running and reporting its current version string.
    """
    return {"status": "ok", "version": config.SIDECAR_VERSION}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=config.SIDECAR_PORT,
        log_level="info",
    )
