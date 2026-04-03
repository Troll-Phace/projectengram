"""FastAPI router for application configuration key-value store.

Provides endpoints for listing all config entries and upserting
individual entries by key.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlmodel import Session, SQLModel, select

from db.session import get_session
from models import Config

# ---------------------------------------------------------------------------
# Pydantic request / response schemas
# ---------------------------------------------------------------------------


class ConfigUpdate(SQLModel):
    """Request body for upserting a config entry."""

    value: str | None = None


class ConfigPublic(SQLModel):
    """Response model exposing all config data columns."""

    key: str
    value: str | None = None
    updated_at: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/config", tags=["config"])


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string.

    Returns:
        A string in ``YYYY-MM-DDTHH:MM:SSZ`` format.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ConfigPublic])
def list_config(
    *,
    session: Session = Depends(get_session),
) -> list[Config]:
    """List all configuration entries.

    Args:
        session: The database session (injected).

    Returns:
        A list of all config key-value entries.
    """
    return list(session.exec(select(Config)).all())


@router.patch("/{key}", response_model=ConfigPublic)
def upsert_config(
    *,
    session: Session = Depends(get_session),
    key: str,
    data: ConfigUpdate,
) -> Config:
    """Update or create a config entry by key.

    Uses upsert semantics: if the key already exists its value and
    ``updated_at`` timestamp are updated; otherwise a new entry is
    created.

    Args:
        session: The database session (injected).
        key: The configuration key to update or create.
        data: The update payload containing the new value.

    Returns:
        The upserted config entry.
    """
    now = _now_iso()
    config = session.get(Config, key)

    if config is not None:
        config.value = data.value
        config.updated_at = now
    else:
        config = Config(key=key, value=data.value, updated_at=now)

    session.add(config)
    session.commit()
    session.refresh(config)
    return config
