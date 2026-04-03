"""Database migration runner using raw sqlite3 and PRAGMA user_version.

Discovers numbered SQL migration files, compares against the current
``user_version`` stored in the database, and applies pending scripts in
ascending order.  Uses raw ``sqlite3`` rather than SQLAlchemy because
the migrator must run *before* the ORM engine is constructed.
"""

import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_MIGRATION_PATTERN = re.compile(r"^(\d{4})_.*\.sql$")
_PRAGMA_USER_VERSION_RE = re.compile(
    r"^\s*PRAGMA\s+user_version\s*=\s*\d+\s*;\s*$",
    re.IGNORECASE | re.MULTILINE,
)


class DatabaseMigrator:
    """Apply pending SQL migrations tracked by ``PRAGMA user_version``.

    Args:
        db_path: Path to the SQLite database file.
        migrations_dir: Directory containing numbered ``NNNN_*.sql`` files.
    """

    def __init__(self, db_path: str | Path, migrations_dir: str | Path) -> None:
        self._db_path = Path(db_path)
        self._migrations_dir = Path(migrations_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def migrate(self) -> bool:
        """Run all pending migrations.

        Returns:
            ``True`` if all pending migrations applied successfully (or none
            were pending).  ``False`` if any migration failed.
        """
        try:
            conn = sqlite3.connect(str(self._db_path))
            try:
                conn.execute("PRAGMA foreign_keys = ON")

                current_version = self._get_current_version(conn)
                migrations = self._discover_migrations()
                pending = [
                    (version, path)
                    for version, path in migrations
                    if version > current_version
                ]

                if not pending:
                    logger.info(
                        "Database at version %d — no pending migrations.",
                        current_version,
                    )
                    return True

                for version, script_path in pending:
                    logger.info(
                        "Applying migration %04d (%s) ...",
                        version,
                        script_path.name,
                    )
                    self._apply_migration(conn, version, script_path)

                final_version = self._get_current_version(conn)
                logger.info(
                    "Migrations complete: version %d -> %d.",
                    current_version,
                    final_version,
                )
                return True
            finally:
                conn.close()

        except Exception:
            logger.exception("Migration failed.")
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_current_version(self, conn: sqlite3.Connection) -> int:
        """Read the current schema version from ``PRAGMA user_version``.

        Args:
            conn: An open sqlite3 connection.

        Returns:
            The integer user_version (0 if never set).
        """
        row = conn.execute("PRAGMA user_version").fetchone()
        return row[0] if row else 0

    def _discover_migrations(self) -> list[tuple[int, Path]]:
        """Glob for migration SQL files and sort by version number.

        Migration files must match the pattern ``NNNN_<description>.sql``
        where ``NNNN`` is a zero-padded 4-digit version number.

        Returns:
            A list of ``(version, path)`` tuples sorted ascending by version.
        """
        results: list[tuple[int, Path]] = []
        for sql_file in self._migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"):
            match = _MIGRATION_PATTERN.match(sql_file.name)
            if match:
                version = int(match.group(1))
                results.append((version, sql_file))
        results.sort(key=lambda t: t[0])
        return results

    def _apply_migration(
        self,
        conn: sqlite3.Connection,
        version: int,
        script_path: Path,
    ) -> None:
        """Execute a single migration script and update ``user_version``.

        The method strips any ``PRAGMA user_version`` lines from the SQL
        so that version tracking is handled programmatically.

        Args:
            conn: An open sqlite3 connection.
            version: The version number to set after successful execution.
            script_path: Path to the ``.sql`` file to execute.

        Raises:
            sqlite3.Error: If the SQL execution fails.
        """
        raw_sql = script_path.read_text(encoding="utf-8")
        cleaned_sql = _PRAGMA_USER_VERSION_RE.sub("", raw_sql)
        conn.executescript(cleaned_sql)
        conn.execute(f"PRAGMA user_version = {version}")
