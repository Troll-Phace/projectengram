"""FastAPI router for project CRUD operations.

Provides endpoints for listing, creating, updating, and soft-deleting
projects.  Filtering by status, primary language, and tag is supported
on the list endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from db.session import get_session
from models import Project, ProjectTag, Tag
from utils.time import now_iso

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_STATUSES = {"active", "paused", "archived", "idea"}

# ---------------------------------------------------------------------------
# Pydantic request / response schemas
# ---------------------------------------------------------------------------


class ProjectCreate(SQLModel):
    """Request body for creating a new project."""

    name: str
    status: str = "active"
    path: str | None = None
    description: str | None = None
    primary_language: str | None = None
    languages: str | None = None
    frameworks: str | None = None
    package_manager: str | None = None
    git_remote_url: str | None = None
    git_branch: str | None = None
    color_override: str | None = None
    icon_override: str | None = None
    notes: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Ensure status is one of the allowed values.

        Args:
            v: The status value to validate.

        Returns:
            The validated status string.

        Raises:
            ValueError: If status is not in the allowed set.
        """
        if v not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{v}'. Must be one of: {sorted(_VALID_STATUSES)}"
            )
        return v


class ProjectUpdate(SQLModel):
    """Request body for partially updating an existing project."""

    name: str | None = None
    status: str | None = None
    path: str | None = None
    description: str | None = None
    primary_language: str | None = None
    languages: str | None = None
    frameworks: str | None = None
    package_manager: str | None = None
    git_remote_url: str | None = None
    git_branch: str | None = None
    color_override: str | None = None
    icon_override: str | None = None
    notes: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        """Ensure status is one of the allowed values when provided.

        Args:
            v: The status value to validate, or ``None`` if not provided.

        Returns:
            The validated status string, or ``None``.

        Raises:
            ValueError: If status is not ``None`` and not in the allowed set.
        """
        if v is not None and v not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{v}'. Must be one of: {sorted(_VALID_STATUSES)}"
            )
        return v


class ProjectPublic(SQLModel):
    """Response model exposing all project data columns."""

    id: str
    name: str
    path: str | None = None
    description: str | None = None
    status: str
    primary_language: str | None = None
    languages: str | None = None
    frameworks: str | None = None
    package_manager: str | None = None
    loc: int | None = None
    file_count: int | None = None
    size_bytes: int | None = None
    git_remote_url: str | None = None
    git_branch: str | None = None
    git_dirty: bool
    git_last_commit_hash: str | None = None
    git_last_commit_date: str | None = None
    git_last_commit_msg: str | None = None
    git_branch_count: int | None = None
    color_override: str | None = None
    icon_override: str | None = None
    notes: str | None = None
    missing: bool
    deleted_at: str | None = None
    last_scanned_at: str | None = None
    last_opened_at: str | None = None
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/projects", tags=["projects"])

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ProjectPublic])
def list_projects(
    *,
    session: Session = Depends(get_session),
    status: str | None = Query(default=None, description="Filter by project status"),
    language: str | None = Query(
        default=None, description="Filter by primary language"
    ),
    tag: str | None = Query(default=None, description="Filter by tag name"),
) -> list[Project]:
    """List all non-deleted projects with optional filters.

    Args:
        session: The database session (injected).
        status: Optional status filter (active, paused, archived, idea).
        language: Optional primary language filter.
        tag: Optional tag name filter.

    Returns:
        A list of projects matching the given filters.
    """
    statement = select(Project).where(Project.deleted_at.is_(None))  # type: ignore[union-attr]

    if status is not None:
        statement = statement.where(Project.status == status)

    if language is not None:
        statement = statement.where(Project.primary_language == language)

    if tag is not None:
        statement = (
            statement.join(ProjectTag, Project.id == ProjectTag.project_id)
            .join(Tag, ProjectTag.tag_id == Tag.id)
            .where(Tag.name == tag)
        )

    return list(session.exec(statement).all())


@router.get("/{project_id}", response_model=ProjectPublic)
def get_project(
    *,
    session: Session = Depends(get_session),
    project_id: str,
) -> Project:
    """Retrieve a single project by ID.

    Returns even soft-deleted projects so the frontend can display
    deleted context when needed.

    Args:
        session: The database session (injected).
        project_id: The ULID of the project to retrieve.

    Returns:
        The requested project.

    Raises:
        HTTPException: 404 if the project does not exist.
    """
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("", response_model=ProjectPublic, status_code=201)
def create_project(
    *,
    session: Session = Depends(get_session),
    data: ProjectCreate,
) -> Project:
    """Create a new project.

    Args:
        session: The database session (injected).
        data: The project creation payload.

    Returns:
        The newly created project.

    Raises:
        HTTPException: 409 if a project with the same path already exists.
    """
    now = now_iso()
    project = Project(**data.model_dump(), created_at=now, updated_at=now)
    session.add(project)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A project with this path already exists"
        )
    session.refresh(project)
    return project


@router.patch("/{project_id}", response_model=ProjectPublic)
def update_project(
    *,
    session: Session = Depends(get_session),
    project_id: str,
    data: ProjectUpdate,
) -> Project:
    """Partially update an existing project.

    Only fields included in the request body are modified; omitted
    fields remain unchanged.  The ``updated_at`` timestamp is always
    refreshed.

    Args:
        session: The database session (injected).
        project_id: The ULID of the project to update.
        data: The partial update payload.

    Returns:
        The updated project.

    Raises:
        HTTPException: 404 if the project does not exist.
        HTTPException: 409 if the updated path conflicts with an existing project.
    """
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    update_data = data.model_dump(exclude_unset=True)
    update_data["updated_at"] = now_iso()
    project.sqlmodel_update(update_data)

    session.add(project)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A project with this path already exists"
        )
    session.refresh(project)
    return project


@router.delete("/{project_id}", response_model=ProjectPublic)
def delete_project(
    *,
    session: Session = Depends(get_session),
    project_id: str,
) -> Project:
    """Soft-delete a project by setting its ``deleted_at`` timestamp.

    Idempotent: if the project is already soft-deleted the existing
    record is returned without modification.

    Args:
        session: The database session (injected).
        project_id: The ULID of the project to soft-delete.

    Returns:
        The soft-deleted project.

    Raises:
        HTTPException: 404 if the project does not exist.
    """
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.deleted_at is not None:
        return project

    now = now_iso()
    project.deleted_at = now
    project.updated_at = now
    session.add(project)
    session.commit()
    session.refresh(project)
    return project
