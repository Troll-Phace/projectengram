"""SQLModel ORM models for the ``clusters`` and ``project_clusters`` tables.

``ProjectCluster`` is the many-to-many join model and MUST be defined
before ``Cluster`` so that SQLAlchemy can resolve the forward reference
at class creation time.
"""

from sqlmodel import Field, Relationship, SQLModel

from utils.ulid import generate_ulid


# =============================================================================
# Join table model — must be defined first
# =============================================================================


class ProjectCluster(SQLModel, table=True):
    """Many-to-many join between projects and clusters."""

    __tablename__ = "project_clusters"

    project_id: str = Field(
        foreign_key="projects.id",
        primary_key=True,
        ondelete="CASCADE",
    )
    cluster_id: str = Field(
        foreign_key="clusters.id",
        primary_key=True,
        ondelete="CASCADE",
    )

    # --- Relationships -----------------------------------------------------------

    project: "Project" = Relationship(back_populates="cluster_links")
    cluster: "Cluster" = Relationship(back_populates="project_links")


# =============================================================================
# Cluster entity
# =============================================================================


class Cluster(SQLModel, table=True):
    """Visual grouping region on the graph canvas."""

    __tablename__ = "clusters"

    id: str = Field(default_factory=generate_ulid, primary_key=True)
    name: str
    color: str | None = None
    opacity: float = 0.15
    collapsed: bool = False
    created_at: str
    updated_at: str

    # --- Relationships -----------------------------------------------------------

    project_links: list[ProjectCluster] = Relationship(
        back_populates="cluster",
        passive_deletes="all",
    )
