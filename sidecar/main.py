"""Engram sidecar — FastAPI application entry point.

Starts the async HTTP + WebSocket server that the Tauri desktop shell
communicates with over localhost.
"""

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle.

    Startup:
        - Run database migrations (blocks startup on failure).
        - (Phase 15) Start the file watcher background task.
        - (Phase 14) Trigger an initial full scan.

    Shutdown:
        - (Phase 15) Cancel the file watcher task.
        - (Phase 14) Gracefully shut down the scan orchestrator.
    """
    migrator = DatabaseMigrator(config.DB_PATH, config.MIGRATIONS_DIR)
    if not migrator.migrate():
        raise RuntimeError("Database migration failed — refusing to start.")

    # TODO: Phase 15 — start file watcher background task
    # TODO: Phase 14 — trigger initial full scan
    yield
    # TODO: Phase 15 — cancel file watcher task
    # TODO: Phase 14 — shut down scan orchestrator


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
