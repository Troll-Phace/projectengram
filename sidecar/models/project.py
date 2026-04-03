"""SQLModel ORM model for the ``projects`` table.

The central entity in Engram — each row represents a coding project
discovered by the scanner or manually added by the user.  The 28 data
columns map 1:1 to the schema defined in ``0001_init.sql``.
"""

from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from utils.ulid import generate_ulid


class Project(SQLModel, table=True):
    """A coding project tracked by Engram."""

    __tablename__ = "projects"

    # --- Primary key -------------------------------------------------------------

    id: str = Field(default_factory=generate_ulid, primary_key=True)

    # --- Required strings --------------------------------------------------------

    name: str
    created_at: str
    updated_at: str

    # --- Defaults ----------------------------------------------------------------

    status: str = "active"
    git_dirty: bool = False
    missing: bool = False

    # --- Optional strings --------------------------------------------------------

    path: str | None = None
    description: str | None = None
    primary_language: str | None = None
    languages: str | None = None  # JSON object
    frameworks: str | None = None  # JSON array
    package_manager: str | None = None
    git_remote_url: str | None = None
    git_branch: str | None = None
    git_last_commit_hash: str | None = None
    git_last_commit_date: str | None = None
    git_last_commit_msg: str | None = None
    color_override: str | None = None
    icon_override: str | None = None
    notes: str | None = None
    deleted_at: str | None = None
    last_scanned_at: str | None = None
    last_opened_at: str | None = None

    # --- Optional integers -------------------------------------------------------

    loc: int | None = None
    file_count: int | None = None
    size_bytes: int | None = None
    git_branch_count: int | None = None

    # --- Relationships -----------------------------------------------------------

    source_edges: list["Edge"] = Relationship(
        back_populates="source",
        sa_relationship_kwargs={"foreign_keys": "[Edge.source_id]"},
        passive_deletes="all",
    )
    target_edges: list["Edge"] = Relationship(
        back_populates="target",
        sa_relationship_kwargs={"foreign_keys": "[Edge.target_id]"},
        passive_deletes="all",
    )
    tag_links: list["ProjectTag"] = Relationship(
        back_populates="project",
        passive_deletes="all",
    )
    cluster_links: list["ProjectCluster"] = Relationship(
        back_populates="project",
        passive_deletes="all",
    )
    node_position: Optional["NodePosition"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"uselist": False},
        passive_deletes="all",
    )
