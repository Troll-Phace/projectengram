"""SQLModel ORM model for the ``node_positions`` table.

Persists x/y coordinates and pinned state for each project node on the
graph canvas. The primary key is also a foreign key referencing the
projects table.
"""

from sqlmodel import Field, Relationship, SQLModel


class NodePosition(SQLModel, table=True):
    """Persisted graph layout position for a single project node."""

    __tablename__ = "node_positions"

    project_id: str = Field(
        foreign_key="projects.id",
        primary_key=True,
        ondelete="CASCADE",
    )
    x: float
    y: float
    pinned: bool = False
    updated_at: str

    # --- Relationships -----------------------------------------------------------

    project: "Project" = Relationship(back_populates="node_position")
