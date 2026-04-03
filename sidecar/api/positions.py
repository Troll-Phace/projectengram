"""FastAPI router for node-position CRUD operations.

Provides endpoints for listing all positions, updating a single position,
and batch-upserting positions after a layout simulation.  These
positions are persisted so the graph canvas can restore node layout on
app load.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel, select

from db.session import get_session
from models import NodePosition, Project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string.

    Returns:
        A string in ``YYYY-MM-DDTHH:MM:SSZ`` format.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Pydantic request / response schemas
# ---------------------------------------------------------------------------


class PositionUpdate(SQLModel):
    """Request body for partially updating a single node position."""

    x: float | None = None
    y: float | None = None
    pinned: bool | None = None


class PositionPublic(SQLModel):
    """Response model exposing all node-position data columns."""

    project_id: str
    x: float
    y: float
    pinned: bool
    updated_at: str


class PositionBatchItem(SQLModel):
    """A single position entry within a batch-update request."""

    project_id: str
    x: float
    y: float
    pinned: bool = False


class PositionBatchRequest(SQLModel):
    """Request body for batch-upserting node positions."""

    positions: list[PositionBatchItem]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/positions", tags=["positions"])

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[PositionPublic])
def list_positions(
    *,
    session: Session = Depends(get_session),
) -> list[NodePosition]:
    """List all persisted node positions.

    Used on app load to restore the graph layout from the last session.

    Args:
        session: The database session (injected).

    Returns:
        A list of all node positions.
    """
    return list(session.exec(select(NodePosition)).all())


@router.patch("/{project_id}", response_model=PositionPublic)
def update_position(
    *,
    session: Session = Depends(get_session),
    project_id: str,
    data: PositionUpdate,
) -> NodePosition:
    """Partially update an existing node position.

    Only fields included in the request body are modified; omitted
    fields remain unchanged.  The ``updated_at`` timestamp is always
    refreshed.

    Args:
        session: The database session (injected).
        project_id: The project ID whose position to update.
        data: The partial update payload.

    Returns:
        The updated node position.

    Raises:
        HTTPException: 404 if the position does not exist.
    """
    position = session.get(NodePosition, project_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Position not found")

    update_data = data.model_dump(exclude_unset=True)
    update_data["updated_at"] = _now_iso()
    position.sqlmodel_update(update_data)

    session.add(position)
    session.commit()
    session.refresh(position)
    return position


@router.post("/batch", response_model=list[PositionPublic])
def batch_upsert_positions(
    *,
    session: Session = Depends(get_session),
    data: PositionBatchRequest,
) -> list[NodePosition]:
    """Batch upsert node positions.

    For each item in the request, creates a new ``NodePosition`` if one
    does not exist for the given ``project_id``, or updates the existing
    record.  All writes happen in a single transaction.

    Args:
        session: The database session (injected).
        data: The batch-update payload containing a list of positions.

    Returns:
        A list of all upserted node positions.

    Raises:
        HTTPException: 400 if any ``project_id`` does not reference an
            existing project.
    """
    # --- Validate all project IDs before writing --------------------------
    for item in data.positions:
        project = session.get(Project, item.project_id)
        if project is None:
            raise HTTPException(
                status_code=400,
                detail=f"Project not found: {item.project_id}",
            )

    # --- Upsert each position ---------------------------------------------
    now = _now_iso()
    results: list[NodePosition] = []

    for item in data.positions:
        position = session.get(NodePosition, item.project_id)
        if position is not None:
            position.sqlmodel_update(
                {
                    "x": item.x,
                    "y": item.y,
                    "pinned": item.pinned,
                    "updated_at": now,
                }
            )
        else:
            position = NodePosition(
                project_id=item.project_id,
                x=item.x,
                y=item.y,
                pinned=item.pinned,
                updated_at=now,
            )
        session.add(position)
        results.append(position)

    session.commit()
    for pos in results:
        session.refresh(pos)

    return results
