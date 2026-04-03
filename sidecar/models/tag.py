"""SQLModel ORM models for the ``tags`` and ``project_tags`` tables.

``ProjectTag`` is the many-to-many join model and MUST be defined before
``Tag`` so that SQLAlchemy can resolve the forward reference at class
creation time.
"""

from sqlmodel import Field, Relationship, SQLModel

from utils.ulid import generate_ulid


# =============================================================================
# Join table model — must be defined first
# =============================================================================


class ProjectTag(SQLModel, table=True):
    """Many-to-many join between projects and tags."""

    __tablename__ = "project_tags"

    project_id: str = Field(
        foreign_key="projects.id",
        primary_key=True,
        ondelete="CASCADE",
    )
    tag_id: str = Field(
        foreign_key="tags.id",
        primary_key=True,
        ondelete="CASCADE",
    )

    # --- Relationships -----------------------------------------------------------

    project: "Project" = Relationship(back_populates="tag_links")
    tag: "Tag" = Relationship(back_populates="project_links")


# =============================================================================
# Tag entity
# =============================================================================


class Tag(SQLModel, table=True):
    """User-defined label that can be attached to one or more projects."""

    __tablename__ = "tags"

    id: str = Field(default_factory=generate_ulid, primary_key=True)
    name: str
    color: str | None = None
    created_at: str

    # --- Relationships -----------------------------------------------------------

    project_links: list[ProjectTag] = Relationship(
        back_populates="tag",
        passive_deletes="all",
    )
