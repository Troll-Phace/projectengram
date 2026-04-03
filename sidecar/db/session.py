"""FastAPI dependency for SQLModel session injection."""

from collections.abc import Generator

from sqlmodel import Session

from db.engine import engine


def get_session() -> Generator[Session, None, None]:
    """Yield a SQLModel session for FastAPI dependency injection.

    Yields:
        A SQLModel ``Session`` bound to the default engine.
    """
    with Session(engine) as session:
        yield session
