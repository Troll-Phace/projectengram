"""FastAPI router for edge CRUD operations.

Provides endpoints for listing, creating, updating, and deleting
edges between projects.  Only manual edges can be created or deleted
through the API; auto-computed edges are managed by the scanning
pipeline.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from db.session import get_session
from models import Edge, Project
from utils.time import now_iso

# ---------------------------------------------------------------------------
# Pydantic request / response schemas
# ---------------------------------------------------------------------------


class EdgeCreate(SQLModel):
    """Request body for creating a new manual edge."""

    source_id: str
    target_id: str
    weight: float = 0.5
    label: str | None = None
    color_override: str | None = None
    directed: bool = False

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, v: float) -> float:
        """Ensure weight is between 0.0 and 1.0 inclusive.

        Args:
            v: The weight value to validate.

        Returns:
            The validated weight.

        Raises:
            ValueError: If weight is outside the allowed range.
        """
        if not 0.0 <= v <= 1.0:
            raise ValueError("Weight must be between 0.0 and 1.0")
        return v


class EdgeUpdate(SQLModel):
    """Request body for partially updating an existing edge."""

    weight: float | None = None
    label: str | None = None
    color_override: str | None = None
    directed: bool | None = None

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, v: float | None) -> float | None:
        """Ensure weight is between 0.0 and 1.0 inclusive when provided.

        Args:
            v: The weight value to validate, or ``None`` if not provided.

        Returns:
            The validated weight, or ``None``.

        Raises:
            ValueError: If weight is not ``None`` and outside the allowed range.
        """
        if v is not None and not 0.0 <= v <= 1.0:
            raise ValueError("Weight must be between 0.0 and 1.0")
        return v


class EdgePublic(SQLModel):
    """Response model exposing all edge data columns."""

    id: str
    source_id: str
    target_id: str
    edge_type: str
    weight: float
    label: str | None = None
    color_override: str | None = None
    directed: bool
    edge_metadata: str | None = None
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/edges", tags=["edges"])

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[EdgePublic])
def list_edges(
    *,
    session: Session = Depends(get_session),
    source_id: str | None = Query(default=None, description="Filter by source project ID"),
    target_id: str | None = Query(default=None, description="Filter by target project ID"),
    edge_type: str | None = Query(default=None, description="Filter by edge type"),
) -> list[Edge]:
    """List all edges with optional filters.

    Args:
        session: The database session (injected).
        source_id: Optional source project ID filter.
        target_id: Optional target project ID filter.
        edge_type: Optional edge type filter.

    Returns:
        A list of edges matching the given filters.
    """
    statement = select(Edge)

    if source_id is not None:
        statement = statement.where(Edge.source_id == source_id)

    if target_id is not None:
        statement = statement.where(Edge.target_id == target_id)

    if edge_type is not None:
        statement = statement.where(Edge.edge_type == edge_type)

    return list(session.exec(statement).all())


@router.post("", response_model=EdgePublic, status_code=201)
def create_edge(
    *,
    session: Session = Depends(get_session),
    data: EdgeCreate,
) -> Edge:
    """Create a new manual edge between two projects.

    The ``edge_type`` is always set to ``"manual"`` regardless of any
    client input.  Both the source and target projects must exist.

    Args:
        session: The database session (injected).
        data: The edge creation payload.

    Returns:
        The newly created edge.

    Raises:
        HTTPException: 409 if source and target are the same project.
        HTTPException: 404 if either the source or target project does not exist.
        HTTPException: 409 if the edge violates a unique constraint.
    """
    if data.source_id == data.target_id:
        raise HTTPException(
            status_code=409, detail="Self-referential edges are not allowed"
        )

    source = session.get(Project, data.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source project not found")

    target = session.get(Project, data.target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target project not found")

    now = now_iso()
    edge = Edge(
        **data.model_dump(),
        edge_type="manual",
        created_at=now,
        updated_at=now,
    )
    session.add(edge)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="An edge with this source, target, and type already exists",
        )
    session.refresh(edge)
    return edge


@router.patch("/{edge_id}", response_model=EdgePublic)
def update_edge(
    *,
    session: Session = Depends(get_session),
    edge_id: str,
    data: EdgeUpdate,
) -> Edge:
    """Partially update an existing edge.

    Only fields included in the request body are modified; omitted
    fields remain unchanged.  The ``updated_at`` timestamp is always
    refreshed.

    Args:
        session: The database session (injected).
        edge_id: The ULID of the edge to update.
        data: The partial update payload.

    Returns:
        The updated edge.

    Raises:
        HTTPException: 404 if the edge does not exist.
    """
    edge = session.get(Edge, edge_id)
    if edge is None:
        raise HTTPException(status_code=404, detail="Edge not found")

    if edge.edge_type != "manual":
        raise HTTPException(
            status_code=403,
            detail="Only manual edges can be modified via the API",
        )

    update_data = data.model_dump(exclude_unset=True)
    update_data["updated_at"] = now_iso()
    edge.sqlmodel_update(update_data)

    session.add(edge)
    session.commit()
    session.refresh(edge)
    return edge


@router.delete("/{edge_id}")
def delete_edge(
    *,
    session: Session = Depends(get_session),
    edge_id: str,
) -> dict[str, bool]:
    """Hard-delete an edge.

    Args:
        session: The database session (injected).
        edge_id: The ULID of the edge to delete.

    Returns:
        A confirmation dict ``{"ok": True}``.

    Raises:
        HTTPException: 404 if the edge does not exist.
    """
    edge = session.get(Edge, edge_id)
    if edge is None:
        raise HTTPException(status_code=404, detail="Edge not found")

    if edge.edge_type != "manual":
        raise HTTPException(
            status_code=403,
            detail="Only manual edges can be deleted via the API",
        )

    session.delete(edge)
    session.commit()
    return {"ok": True}
