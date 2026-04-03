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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle.

    Startup responsibilities (added in later phases):
        - Run database migrations
        - Start the file watcher background task
        - Trigger an initial full scan

    Shutdown responsibilities (added in later phases):
        - Cancel the file watcher task
        - Gracefully shut down the scan orchestrator
    """
    # TODO: Phase 4 — run database migrations
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
