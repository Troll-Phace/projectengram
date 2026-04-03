"""SQLModel ORM model for the ``config`` table.

Maps the key-value application settings store. Keys are user-defined
strings (not ULIDs) and values are JSON-encoded TEXT.
"""

from sqlmodel import Field, SQLModel


class Config(SQLModel, table=True):
    """Key-value application configuration entry."""

    __tablename__ = "config"

    key: str = Field(primary_key=True)
    value: str | None = None
    updated_at: str
