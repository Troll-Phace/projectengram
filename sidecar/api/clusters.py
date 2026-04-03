"""FastAPI router for cluster CRUD and membership operations.

Provides endpoints for listing, creating, updating, and deleting
clusters, as well as managing which projects belong to each cluster
via the ``project_clusters`` join table.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from db.session import get_session
from models import Cluster, Project, ProjectCluster

# ---------------------------------------------------------------------------
# Pydantic request / response schemas
# ---------------------------------------------------------------------------


class ClusterCreate(SQLModel):
    """Request body for creating a new cluster."""

    name: str
    color: str | None = None
    opacity: float = 0.15
    collapsed: bool = False

    @field_validator("opacity")
    @classmethod
    def validate_opacity(cls, v: float) -> float:
        """Ensure opacity is between 0.0 and 1.0 inclusive.

        Args:
            v: The opacity value to validate.

        Returns:
            The validated opacity.

        Raises:
            ValueError: If opacity is outside the allowed range.
        """
        if not 0.0 <= v <= 1.0:
            raise ValueError("Opacity must be between 0.0 and 1.0")
        return v


class ClusterUpdate(SQLModel):
    """Request body for partially updating an existing cluster."""

    name: str | None = None
    color: str | None = None
    opacity: float | None = None
    collapsed: bool | None = None

    @field_validator("opacity")
    @classmethod
    def validate_opacity(cls, v: float | None) -> float | None:
        """Ensure opacity is between 0.0 and 1.0 inclusive when provided.

        Args:
            v: The opacity value to validate, or ``None`` if not provided.

        Returns:
            The validated opacity, or ``None``.

        Raises:
            ValueError: If opacity is not ``None`` and outside the allowed range.
        """
        if v is not None and not 0.0 <= v <= 1.0:
            raise ValueError("Opacity must be between 0.0 and 1.0")
        return v


class ClusterPublic(SQLModel):
    """Response model exposing all cluster data columns."""

    id: str
    name: str
    color: str | None = None
    opacity: float
    collapsed: bool
    created_at: str
    updated_at: str


class ClusterMemberAdd(SQLModel):
    """Request body for adding a project to a cluster."""

    project_id: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/clusters", tags=["clusters"])


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string.

    Returns:
        A string in ``YYYY-MM-DDTHH:MM:SSZ`` format.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Cluster CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ClusterPublic])
def list_clusters(
    *,
    session: Session = Depends(get_session),
) -> list[Cluster]:
    """List all clusters.

    Args:
        session: The database session (injected).

    Returns:
        A list of all clusters.
    """
    statement = select(Cluster)
    return list(session.exec(statement).all())


@router.post("", response_model=ClusterPublic, status_code=201)
def create_cluster(
    *,
    session: Session = Depends(get_session),
    data: ClusterCreate,
) -> Cluster:
    """Create a new cluster.

    Args:
        session: The database session (injected).
        data: The cluster creation payload.

    Returns:
        The newly created cluster.
    """
    now = _now_iso()
    cluster = Cluster(**data.model_dump(), created_at=now, updated_at=now)
    session.add(cluster)
    session.commit()
    session.refresh(cluster)
    return cluster


@router.patch("/{cluster_id}", response_model=ClusterPublic)
def update_cluster(
    *,
    session: Session = Depends(get_session),
    cluster_id: str,
    data: ClusterUpdate,
) -> Cluster:
    """Partially update an existing cluster.

    Only fields included in the request body are modified; omitted
    fields remain unchanged.  The ``updated_at`` timestamp is always
    refreshed.

    Args:
        session: The database session (injected).
        cluster_id: The ULID of the cluster to update.
        data: The partial update payload.

    Returns:
        The updated cluster.

    Raises:
        HTTPException: 404 if the cluster does not exist.
    """
    cluster = session.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found")

    update_data = data.model_dump(exclude_unset=True)
    update_data["updated_at"] = _now_iso()
    cluster.sqlmodel_update(update_data)

    session.add(cluster)
    session.commit()
    session.refresh(cluster)
    return cluster


@router.delete("/{cluster_id}")
def delete_cluster(
    *,
    session: Session = Depends(get_session),
    cluster_id: str,
) -> dict[str, bool]:
    """Hard-delete a cluster.

    Associated ``project_clusters`` rows are removed automatically via
    the ``ON DELETE CASCADE`` foreign-key constraint.

    Args:
        session: The database session (injected).
        cluster_id: The ULID of the cluster to delete.

    Returns:
        A confirmation dict ``{"ok": True}``.

    Raises:
        HTTPException: 404 if the cluster does not exist.
    """
    cluster = session.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found")

    session.delete(cluster)
    session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Cluster membership endpoints
# ---------------------------------------------------------------------------


@router.post("/{cluster_id}/projects", status_code=201)
def add_project_to_cluster(
    *,
    session: Session = Depends(get_session),
    cluster_id: str,
    data: ClusterMemberAdd,
) -> dict[str, bool]:
    """Add a project to a cluster.

    Args:
        session: The database session (injected).
        cluster_id: The ULID of the cluster.
        data: The membership payload containing the project ID.

    Returns:
        A confirmation dict ``{"ok": True}``.

    Raises:
        HTTPException: 404 if the cluster does not exist.
        HTTPException: 404 if the project does not exist.
        HTTPException: 409 if the project is already in this cluster.
    """
    cluster = session.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found")

    project = session.get(Project, data.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    link = ProjectCluster(project_id=data.project_id, cluster_id=cluster_id)
    session.add(link)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Project already in this cluster"
        )
    return {"ok": True}


@router.delete("/{cluster_id}/projects/{project_id}")
def remove_project_from_cluster(
    *,
    session: Session = Depends(get_session),
    cluster_id: str,
    project_id: str,
) -> dict[str, bool]:
    """Remove a project from a cluster.

    Args:
        session: The database session (injected).
        cluster_id: The ULID of the cluster.
        project_id: The ULID of the project to remove.

    Returns:
        A confirmation dict ``{"ok": True}``.

    Raises:
        HTTPException: 404 if the cluster does not exist.
        HTTPException: 404 if the project is not in this cluster.
    """
    cluster = session.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found")

    statement = select(ProjectCluster).where(
        ProjectCluster.project_id == project_id,
        ProjectCluster.cluster_id == cluster_id,
    )
    link = session.exec(statement).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Project not in this cluster")

    session.delete(link)
    session.commit()
    return {"ok": True}
