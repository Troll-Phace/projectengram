"""FastAPI routers for tag CRUD and project-tag assignment.

Provides endpoints for managing user-defined tags and assigning them
to projects via the ``project_tags`` join table.  Two routers are
exported:

* ``router`` — tag CRUD under ``/api/tags``
* ``project_tags_router`` — tag assignment under ``/api/projects``
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from db.session import get_session
from models import Project, ProjectTag, Tag
from utils.time import now_iso

# ---------------------------------------------------------------------------
# Pydantic request / response schemas
# ---------------------------------------------------------------------------


class TagCreate(SQLModel):
    """Request body for creating a new tag."""

    name: str
    color: str | None = None


class TagUpdate(SQLModel):
    """Request body for partially updating an existing tag."""

    name: str | None = None
    color: str | None = None


class TagPublic(SQLModel):
    """Response model exposing all tag data columns."""

    id: str
    name: str
    color: str | None = None
    created_at: str


class TagAssign(SQLModel):
    """Request body for assigning a tag to a project."""

    tag_id: str


# ---------------------------------------------------------------------------
# Tag CRUD router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[TagPublic])
def list_tags(
    *,
    session: Session = Depends(get_session),
) -> list[Tag]:
    """List all tags.

    Args:
        session: The database session (injected).

    Returns:
        A list of all tags ordered by creation.
    """
    return list(session.exec(select(Tag)).all())


@router.post("", response_model=TagPublic, status_code=201)
def create_tag(
    *,
    session: Session = Depends(get_session),
    data: TagCreate,
) -> Tag:
    """Create a new tag.

    Args:
        session: The database session (injected).
        data: The tag creation payload.

    Returns:
        The newly created tag.

    Raises:
        HTTPException: 409 if a tag with the same name already exists.
    """
    tag = Tag(**data.model_dump(), created_at=now_iso())
    session.add(tag)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A tag with this name already exists"
        )
    session.refresh(tag)
    return tag


@router.patch("/{tag_id}", response_model=TagPublic)
def update_tag(
    *,
    session: Session = Depends(get_session),
    tag_id: str,
    data: TagUpdate,
) -> Tag:
    """Partially update an existing tag.

    Only fields included in the request body are modified; omitted
    fields remain unchanged.

    Args:
        session: The database session (injected).
        tag_id: The ULID of the tag to update.
        data: The partial update payload.

    Returns:
        The updated tag.

    Raises:
        HTTPException: 404 if the tag does not exist.
        HTTPException: 409 if the updated name conflicts with an existing tag.
    """
    tag = session.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")

    update_data = data.model_dump(exclude_unset=True)
    tag.sqlmodel_update(update_data)

    session.add(tag)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A tag with this name already exists"
        )
    session.refresh(tag)
    return tag


@router.delete("/{tag_id}")
def delete_tag(
    *,
    session: Session = Depends(get_session),
    tag_id: str,
) -> dict[str, bool]:
    """Hard-delete a tag.

    Cascade rules on the ``project_tags`` foreign key automatically
    remove all associated project-tag links.

    Args:
        session: The database session (injected).
        tag_id: The ULID of the tag to delete.

    Returns:
        A confirmation dict ``{"ok": True}``.

    Raises:
        HTTPException: 404 if the tag does not exist.
    """
    tag = session.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")

    session.delete(tag)
    session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Project-tag assignment router
# ---------------------------------------------------------------------------

project_tags_router = APIRouter(prefix="/api/projects", tags=["project-tags"])


@project_tags_router.post(
    "/{project_id}/tags", response_model=TagPublic, status_code=201
)
def assign_tag(
    *,
    session: Session = Depends(get_session),
    project_id: str,
    data: TagAssign,
) -> Tag:
    """Assign a tag to a project.

    Args:
        session: The database session (injected).
        project_id: The ULID of the project.
        data: The assignment payload containing the tag ID.

    Returns:
        The assigned tag.

    Raises:
        HTTPException: 404 if the project does not exist.
        HTTPException: 404 if the tag does not exist.
        HTTPException: 409 if the tag is already assigned to this project.
    """
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    tag = session.get(Tag, data.tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")

    link = ProjectTag(project_id=project_id, tag_id=data.tag_id)
    session.add(link)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Tag already assigned to this project"
        )

    session.refresh(tag)
    return tag


@project_tags_router.delete("/{project_id}/tags/{tag_id}")
def remove_tag(
    *,
    session: Session = Depends(get_session),
    project_id: str,
    tag_id: str,
) -> dict[str, bool]:
    """Remove a tag from a project.

    Args:
        session: The database session (injected).
        project_id: The ULID of the project.
        tag_id: The ULID of the tag to unassign.

    Returns:
        A confirmation dict ``{"ok": True}``.

    Raises:
        HTTPException: 404 if the tag is not assigned to this project.
    """
    statement = select(ProjectTag).where(
        ProjectTag.project_id == project_id,
        ProjectTag.tag_id == tag_id,
    )
    link = session.exec(statement).first()
    if link is None:
        raise HTTPException(
            status_code=404, detail="Tag not assigned to this project"
        )

    session.delete(link)
    session.commit()
    return {"ok": True}
