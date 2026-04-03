"""SQLModel engine with SQLite PRAGMA configuration.

Creates a SQLAlchemy engine pre-configured with event listeners that
enforce ``PRAGMA foreign_keys = ON`` and ``PRAGMA journal_mode = WAL``
on every new database connection.
"""

from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import create_engine

import config


def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    """Set required SQLite PRAGMAs on every new connection.

    Must toggle autocommit for ``PRAGMA foreign_keys`` to take effect
    (sqlite3 driver limitation — PRAGMAs issued inside a transaction are
    silently ignored for some settings).

    Args:
        dbapi_connection: The raw DBAPI connection handed out by the pool.
        connection_record: The ``_ConnectionRecord`` for this connection.
    """
    ac = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.close()
    dbapi_connection.autocommit = ac


def get_engine(db_path: str | Path | None = None) -> Engine:
    """Create a SQLModel engine with SQLite PRAGMA listeners.

    Args:
        db_path: Path to the SQLite database file.  Defaults to
            ``config.DB_PATH``.

    Returns:
        A configured SQLAlchemy ``Engine`` instance.
    """
    path = db_path or config.DB_PATH
    eng = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )
    event.listens_for(eng, "connect")(_set_sqlite_pragma)
    return eng


engine: Engine = get_engine()
