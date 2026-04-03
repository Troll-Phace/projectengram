"""SQLModel ORM model for the ``edges`` table.

Represents relationships between projects — either auto-computed by the
scanning pipeline (``auto_tech``, ``auto_dep``) or manually drawn by
the user (``manual``).

NOTE: The database column ``metadata`` conflicts with SQLAlchemy's
reserved ``metadata`` attribute on declarative models.  The Python
attribute is therefore named ``edge_metadata`` and mapped to the
``metadata`` column via ``sa_column``.
"""

from sqlalchemy import Column, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from utils.ulid import generate_ulid


class Edge(SQLModel, table=True):
    """Weighted relationship between two projects."""

    __tablename__ = "edges"
    __table_args__ = (UniqueConstraint("source_id", "target_id", "edge_type"),)

    id: str = Field(default_factory=generate_ulid, primary_key=True)
    source_id: str = Field(foreign_key="projects.id", ondelete="CASCADE")
    target_id: str = Field(foreign_key="projects.id", ondelete="CASCADE")
    edge_type: str
    weight: float
    label: str | None = None
    color_override: str | None = None
    directed: bool = False
    edge_metadata: str | None = Field(
        default=None,
        sa_column=Column("metadata", Text, nullable=True),
    )
    created_at: str
    updated_at: str

    # --- Relationships -----------------------------------------------------------

    source: "Project" = Relationship(
        back_populates="source_edges",
        sa_relationship_kwargs={"foreign_keys": "[Edge.source_id]"},
    )
    target: "Project" = Relationship(
        back_populates="target_edges",
        sa_relationship_kwargs={"foreign_keys": "[Edge.target_id]"},
    )
