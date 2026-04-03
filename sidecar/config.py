"""Engram sidecar configuration constants.

Provides default values for the sidecar server. In later phases, runtime
configuration will be loaded from the SQLite config table, falling back to
these defaults when a key is absent.
"""

SIDECAR_PORT: int = 9721
SIDECAR_VERSION: str = "0.1.0"
APP_TITLE: str = "Engram Sidecar"
DB_FILENAME: str = "engram.db"
PROJECTS_ROOT: str | None = None
