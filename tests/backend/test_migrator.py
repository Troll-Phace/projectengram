"""Tests for the database migration runner (Phase 4)."""

import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure the sidecar directory is on sys.path for bare imports.
_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from db.migrations.migrator import DatabaseMigrator


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Return a path to a fresh temporary SQLite database file."""
    return tmp_path / "test.db"


@pytest.fixture()
def migrations_dir() -> Path:
    """Return the real migrations directory."""
    return Path(_SIDECAR_DIR) / "db" / "migrations"


@pytest.fixture()
def tmp_migrations(tmp_path: Path) -> Path:
    """Return a temporary directory for custom migration fixtures."""
    d = tmp_path / "migrations"
    d.mkdir()
    return d


# -------------------------------------------------------------------------
# DatabaseMigrator — core behavior
# -------------------------------------------------------------------------


class TestMigratorAppliesRealSchema:
    """Test the migrator against the actual 0001_init.sql migration."""

    def test_migrate_returns_true(
        self, tmp_db: Path, migrations_dir: Path
    ) -> None:
        migrator = DatabaseMigrator(tmp_db, migrations_dir)
        assert migrator.migrate() is True

    def test_user_version_set_to_1(
        self, tmp_db: Path, migrations_dir: Path
    ) -> None:
        DatabaseMigrator(tmp_db, migrations_dir).migrate()
        conn = sqlite3.connect(str(tmp_db))
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert version == 1

    def test_tables_created(
        self, tmp_db: Path, migrations_dir: Path
    ) -> None:
        DatabaseMigrator(tmp_db, migrations_dir).migrate()
        conn = sqlite3.connect(str(tmp_db))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        expected = {
            "projects",
            "edges",
            "tags",
            "project_tags",
            "clusters",
            "project_clusters",
            "node_positions",
            "config",
        }
        assert expected.issubset(tables)

    def test_default_config_rows(
        self, tmp_db: Path, migrations_dir: Path
    ) -> None:
        DatabaseMigrator(tmp_db, migrations_dir).migrate()
        conn = sqlite3.connect(str(tmp_db))
        rows = conn.execute("SELECT key FROM config ORDER BY key").fetchall()
        conn.close()
        keys = [r[0] for r in rows]
        assert "projects_root" in keys
        assert "sidecar_port" in keys


class TestMigratorIdempotent:
    """Running migrate() twice should be safe and a no-op the second time."""

    def test_double_migrate_returns_true(
        self, tmp_db: Path, migrations_dir: Path
    ) -> None:
        migrator = DatabaseMigrator(tmp_db, migrations_dir)
        assert migrator.migrate() is True
        assert migrator.migrate() is True

    def test_double_migrate_preserves_version(
        self, tmp_db: Path, migrations_dir: Path
    ) -> None:
        migrator = DatabaseMigrator(tmp_db, migrations_dir)
        migrator.migrate()
        migrator.migrate()
        conn = sqlite3.connect(str(tmp_db))
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert version == 1


class TestMigratorOrdering:
    """Verify that migrations are applied in version-number order."""

    def test_applies_in_order(
        self, tmp_db: Path, tmp_migrations: Path
    ) -> None:
        # Create two migrations that record their execution order.
        (tmp_migrations / "0001_first.sql").write_text(
            "CREATE TABLE _order (step INTEGER);\n"
            "INSERT INTO _order VALUES (1);\n"
        )
        (tmp_migrations / "0002_second.sql").write_text(
            "INSERT INTO _order VALUES (2);\n"
        )
        migrator = DatabaseMigrator(tmp_db, tmp_migrations)
        assert migrator.migrate() is True

        conn = sqlite3.connect(str(tmp_db))
        steps = [
            r[0] for r in conn.execute("SELECT step FROM _order").fetchall()
        ]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert steps == [1, 2]
        assert version == 2

    def test_skips_already_applied(
        self, tmp_db: Path, tmp_migrations: Path
    ) -> None:
        (tmp_migrations / "0001_first.sql").write_text(
            "CREATE TABLE _order (step INTEGER);\n"
            "INSERT INTO _order VALUES (1);\n"
        )
        DatabaseMigrator(tmp_db, tmp_migrations).migrate()

        # Add a second migration after the first run.
        (tmp_migrations / "0002_second.sql").write_text(
            "INSERT INTO _order VALUES (2);\n"
        )
        DatabaseMigrator(tmp_db, tmp_migrations).migrate()

        conn = sqlite3.connect(str(tmp_db))
        steps = [
            r[0] for r in conn.execute("SELECT step FROM _order").fetchall()
        ]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert steps == [1, 2]
        assert version == 2


class TestMigratorFailure:
    """Failed migrations should return False, not raise."""

    def test_bad_sql_returns_false(
        self, tmp_db: Path, tmp_migrations: Path
    ) -> None:
        (tmp_migrations / "0001_bad.sql").write_text(
            "THIS IS NOT VALID SQL;\n"
        )
        migrator = DatabaseMigrator(tmp_db, tmp_migrations)
        assert migrator.migrate() is False

    def test_nonexistent_dir_is_noop(self, tmp_db: Path) -> None:
        migrator = DatabaseMigrator(tmp_db, "/nonexistent/migrations")
        # No matching files means nothing to apply — that's success.
        assert migrator.migrate() is True


class TestMigratorNoPending:
    """An empty migrations dir should be a no-op success."""

    def test_empty_dir_returns_true(
        self, tmp_db: Path, tmp_migrations: Path
    ) -> None:
        migrator = DatabaseMigrator(tmp_db, tmp_migrations)
        assert migrator.migrate() is True


class TestMigratorStripsPragmaUserVersion:
    """The migrator strips PRAGMA user_version lines from SQL files."""

    def test_pragma_stripped_version_set_programmatically(
        self, tmp_db: Path, tmp_migrations: Path
    ) -> None:
        (tmp_migrations / "0001_init.sql").write_text(
            "CREATE TABLE test (id INTEGER PRIMARY KEY);\n"
            "PRAGMA user_version = 999;\n"
        )
        migrator = DatabaseMigrator(tmp_db, tmp_migrations)
        migrator.migrate()

        conn = sqlite3.connect(str(tmp_db))
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        # Should be 1 (from the filename), NOT 999 (from the SQL).
        assert version == 1
