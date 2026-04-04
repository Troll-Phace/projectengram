"""FastAPI router for scan operations.

Provides endpoints for triggering project discovery scans, checking
scan status, and requesting per-project re-scans.  The discovery
endpoint reads the ``projects_root`` config value, enumerates
directories on disk, diffs them against known projects, and updates
the ``missing`` flag accordingly.
"""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, SQLModel, select

from db.session import get_session
from models import Config, Project
from scanner.discovery import DiscoveryResult, KnownProject, discover
from scanner.orchestrator import ScanOrchestrator
from utils.time import now_iso

# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------


class DiscoveredDirectoryPublic(SQLModel):
    """A directory found on disk with no matching DB project."""

    name: str
    path: str


class MissingProjectPublic(SQLModel):
    """A DB project whose directory no longer exists on disk."""

    id: str
    name: str
    path: str


class DiscoveryResultPublic(SQLModel):
    """Response model for the full discovery scan result."""

    new: list[DiscoveredDirectoryPublic]
    missing: list[MissingProjectPublic]
    existing_count: int
    projects_root: str


class ScanStatusPublic(SQLModel):
    """Response model for the current scan status."""

    status: str
    progress: float | None = None
    phase: str | None = None
    total: int | None = None
    completed: int | None = None
    errors: int | None = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/scan", tags=["scan"])


def _resolve_projects_root(raw_value: str) -> Path:
    """Parse a config value into a resolved filesystem path.

    The config table stores values as JSON-encoded strings, so
    ``projects_root`` is typically stored as ``'"~/Documents"'``.
    This helper tries ``json.loads()`` first to unwrap the JSON
    quoting, then falls back to using the raw string directly.

    Args:
        raw_value: The raw ``value`` column from the config table.

    Returns:
        A resolved, expanded ``Path`` object.

    Raises:
        HTTPException: 422 if the resolved path is empty or does not
            exist as a directory on disk.
    """
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, str):
            path_str = parsed
        else:
            path_str = raw_value
    except (json.JSONDecodeError, TypeError):
        path_str = raw_value

    path_str = path_str.strip()
    if not path_str:
        raise HTTPException(
            status_code=422,
            detail="projects_root config value is empty.",
        )

    resolved = Path(path_str).expanduser().resolve()
    if not resolved.is_dir():
        raise HTTPException(
            status_code=422,
            detail=f"projects_root directory does not exist: {resolved}",
        )
    return resolved


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=ScanStatusPublic)
async def scan_status(request: Request) -> ScanStatusPublic:
    """Return the current scan status from the orchestrator.

    Reads live progress data from the ``ScanOrchestrator`` stored on
    ``app.state`` and maps it into the public response model.

    Args:
        request: The incoming request (used to access app state).

    Returns:
        A ``ScanStatusPublic`` with real progress tracking data.
    """
    orchestrator: ScanOrchestrator = request.app.state.orchestrator
    progress = orchestrator.get_status()

    ratio: float | None = None
    if progress.total > 0:
        ratio = progress.completed / progress.total

    return ScanStatusPublic(
        status=progress.status.value,
        progress=ratio,
        phase=progress.phase,
        total=progress.total,
        completed=progress.completed,
        errors=progress.errors if progress.errors > 0 else None,
    )


@router.post("/full", response_model=DiscoveryResultPublic)
async def scan_full(
    *,
    request: Request,
    session: Session = Depends(get_session),
) -> DiscoveryResultPublic:
    """Run a full discovery scan against the configured projects root.

    Reads the ``projects_root`` value from the config table, enumerates
    child directories on disk, diffs them against known (non-deleted)
    projects in the database, and updates the ``missing`` flag on
    affected projects.

    After discovery completes and the response is built, the full
    analysis pipeline is triggered as a background task via the scan
    orchestrator.

    Args:
        request: The incoming request (used to access app state).
        session: The database session (injected).

    Returns:
        A ``DiscoveryResultPublic`` containing new directories,
        missing projects, the count of existing projects, and the
        resolved projects root path.

    Raises:
        HTTPException: 422 if the ``projects_root`` config is not set,
            empty, or points to a non-existent directory.
    """
    # --- Read projects_root from config table ---
    config_entry = session.exec(
        select(Config).where(Config.key == "projects_root")
    ).first()

    if config_entry is None or config_entry.value is None:
        raise HTTPException(
            status_code=422,
            detail="projects_root config is not set. "
            "Configure it via PATCH /api/config/projects_root first.",
        )

    resolved_root = _resolve_projects_root(config_entry.value)

    # --- Query known (non-deleted) projects with a path ---
    known_rows = session.exec(
        select(Project).where(
            Project.deleted_at.is_(None),  # type: ignore[union-attr]
            Project.path.isnot(None),  # type: ignore[union-attr]
        )
    ).all()

    known_projects = [
        KnownProject(id=p.id, name=p.name, path=p.path)  # type: ignore[arg-type]
        for p in known_rows
    ]

    # --- Run discovery (blocking I/O — run in thread pool) ---
    result: DiscoveryResult = await asyncio.to_thread(
        discover, resolved_root, known_projects
    )

    # --- Update missing projects ---
    now = now_iso()
    for missing_kp in result.missing:
        project = session.get(Project, missing_kp.id)
        if project is not None:
            project.missing = True
            project.updated_at = now
            session.add(project)

    # TODO: Phase 16 — broadcast "project_missing" via WebSocket

    # --- Clear missing flag on existing projects ---
    for existing_kp in result.existing:
        project = session.get(Project, existing_kp.id)
        if project is not None and project.missing:
            project.missing = False
            project.updated_at = now
            session.add(project)

    session.commit()

    # TODO: Phase 16 — broadcast "new_project_detected" via WebSocket

    # Trigger full analysis pipeline in the background
    orchestrator: ScanOrchestrator = request.app.state.orchestrator
    asyncio.create_task(orchestrator.trigger_full_scan())

    return DiscoveryResultPublic(
        new=[
            DiscoveredDirectoryPublic(name=d.name, path=d.path)
            for d in result.new
        ],
        missing=[
            MissingProjectPublic(id=kp.id, name=kp.name, path=kp.path)
            for kp in result.missing
        ],
        existing_count=len(result.existing),
        projects_root=result.projects_root,
    )


@router.post("/project/{project_id}", status_code=202)
async def scan_project(
    *,
    request: Request,
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """Trigger a rescan for a single project.

    Validates the project exists and has a path, then enqueues a
    manual-priority rescan via the orchestrator.  Returns immediately
    with HTTP 202 Accepted.

    Args:
        request: The incoming request (used to access app state).
        project_id: The ULID of the project to scan.
        session: The database session (injected).

    Returns:
        A dictionary confirming the scan has been queued.

    Raises:
        HTTPException: 404 if the project does not exist.
        HTTPException: 422 if the project has no path.
    """
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    if project.path is None:
        raise HTTPException(status_code=422, detail="Project has no path.")

    orchestrator: ScanOrchestrator = request.app.state.orchestrator
    await orchestrator.trigger_manual_rescan(project_id)

    return {"detail": "Scan queued.", "project_id": project_id}
