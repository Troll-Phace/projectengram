"""Engram sidecar configuration constants.

Provides default values for the sidecar server. In later phases, runtime
configuration will be loaded from the SQLite config table, falling back to
these defaults when a key is absent.
"""

from pathlib import Path

SIDECAR_PORT: int = 9721
SIDECAR_VERSION: str = "0.1.0"
APP_TITLE: str = "Engram Sidecar"
DB_FILENAME: str = "engram.db"
PROJECTS_ROOT: str | None = None

_SIDECAR_DIR: Path = Path(__file__).resolve().parent
DB_PATH: Path = _SIDECAR_DIR / DB_FILENAME
MIGRATIONS_DIR: Path = _SIDECAR_DIR / "db" / "migrations"
