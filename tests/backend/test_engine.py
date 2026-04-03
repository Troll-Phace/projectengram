"""Tests for the database engine and session layer (Phase 4)."""

import sqlite3
import sys
from pathlib import Path

import pytest
from sqlmodel import Session, text

# Ensure the sidecar directory is on sys.path for bare imports.
_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from db.engine import get_engine
from db.migrations.migrator import DatabaseMigrator
from db.session import get_session


@pytest.fixture()
def migrated_db(tmp_path: Path) -> Path:
    """Create a temporary database with migrations applied."""
    db_path = tmp_path / "test.db"
    migrations_dir = Path(_SIDECAR_DIR) / "db" / "migrations"
    DatabaseMigrator(db_path, migrations_dir).migrate()
    return db_path


# -------------------------------------------------------------------------
# Engine PRAGMA enforcement
# -------------------------------------------------------------------------


class TestEnginePragmas:
    """Verify that PRAGMAs are set on every connection from the engine."""

    def test_foreign_keys_enabled(self, migrated_db: Path) -> None:
        eng = get_engine(migrated_db)
        with eng.connect() as conn:
            result = conn.execute(text("PRAGMA foreign_keys")).fetchone()
            assert result is not None
            assert result[0] == 1

    def test_journal_mode_wal(self, migrated_db: Path) -> None:
        eng = get_engine(migrated_db)
        with eng.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode")).fetchone()
            assert result is not None
            assert result[0] == "wal"

    def test_pragmas_on_new_connections(self, migrated_db: Path) -> None:
        """Each new connection should independently have PRAGMAs set."""
        eng = get_engine(migrated_db)
        for _ in range(3):
            with eng.connect() as conn:
                fk = conn.execute(text("PRAGMA foreign_keys")).fetchone()
                assert fk is not None and fk[0] == 1


# -------------------------------------------------------------------------
# Session dependency
# -------------------------------------------------------------------------


class TestSessionDependency:
    """Verify that get_session yields a working session."""

    def test_session_can_query(self, migrated_db: Path) -> None:
        eng = get_engine(migrated_db)
        with Session(eng) as session:
            tables = session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
            names = {row[0] for row in tables}
            assert "projects" in names

    def test_session_has_foreign_keys(self, migrated_db: Path) -> None:
        eng = get_engine(migrated_db)
        with Session(eng) as session:
            result = session.execute(text("PRAGMA foreign_keys")).fetchone()
            assert result is not None
            assert result[0] == 1


# -------------------------------------------------------------------------
# get_engine with custom path
# -------------------------------------------------------------------------


class TestGetEngineCustomPath:
    """Verify get_engine accepts custom db_path."""

    def test_custom_path_string(self, migrated_db: Path) -> None:
        eng = get_engine(str(migrated_db))
        with eng.connect() as conn:
            result = conn.execute(text("PRAGMA foreign_keys")).fetchone()
            assert result is not None
            assert result[0] == 1

    def test_custom_path_pathlib(self, migrated_db: Path) -> None:
        eng = get_engine(migrated_db)
        with eng.connect() as conn:
            result = conn.execute(text("PRAGMA foreign_keys")).fetchone()
            assert result is not None
            assert result[0] == 1
