"""Tests for the SQLite initial migration schema (0001_init.sql).

Each test creates a fresh in-memory SQLite database, executes the migration,
and validates constraints, columns, defaults, and cascade behavior.
"""

import json
import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_MIGRATION_FILE = _PROJECT_ROOT / "sidecar" / "db" / "migrations" / "0001_init.sql"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_PROJECT_DEFAULTS = dict(
    id="proj_01",
    name="my-project",
    path="/tmp/my-project",
    description="A test project",
    status="active",
    primary_language="python",
    languages='{"python": 1.0}',
    frameworks='["fastapi"]',
    package_manager="pip",
    loc=5000,
    file_count=42,
    size_bytes=102400,
    git_remote_url="https://github.com/test/repo",
    git_branch="main",
    git_dirty=0,
    git_last_commit_hash="abc123",
    git_last_commit_date="2025-01-01T00:00:00Z",
    git_last_commit_msg="init",
    git_branch_count=3,
    color_override=None,
    icon_override=None,
    notes=None,
    missing=0,
    deleted_at=None,
    last_scanned_at="2025-01-01T00:00:00Z",
    last_opened_at=None,
    created_at="2025-01-01T00:00:00Z",
    updated_at="2025-01-01T00:00:00Z",
)

# Ordered column names matching the INSERT statement
_PROJECT_COLUMNS = list(_VALID_PROJECT_DEFAULTS.keys())


def _make_project(**overrides: object) -> dict:
    """Return a valid project row dict with optional overrides."""
    row = {**_VALID_PROJECT_DEFAULTS, **overrides}
    return row


def _insert_project(cur: sqlite3.Cursor, **overrides: object) -> dict:
    """Insert a project row and return the dict used."""
    row = _make_project(**overrides)
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    cur.execute(f"INSERT INTO projects ({cols}) VALUES ({placeholders})", list(row.values()))
    return row


def _insert_tag(cur: sqlite3.Cursor, tag_id: str = "tag_01", name: str = "backend") -> None:
    cur.execute(
        "INSERT INTO tags (id, name, color, created_at) VALUES (?, ?, ?, ?)",
        (tag_id, name, "#FF0000", "2025-01-01T00:00:00Z"),
    )


def _insert_cluster(cur: sqlite3.Cursor, cluster_id: str = "clus_01", name: str = "web") -> None:
    cur.execute(
        "INSERT INTO clusters (id, name, color, opacity, collapsed, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (cluster_id, name, "#00FF00", 0.15, 0, "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    )


def _insert_edge(
    cur: sqlite3.Cursor,
    edge_id: str = "edge_01",
    source_id: str = "proj_01",
    target_id: str = "proj_02",
    edge_type: str = "manual",
    weight: float = 0.5,
) -> None:
    cur.execute(
        "INSERT INTO edges (id, source_id, target_id, edge_type, weight, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (edge_id, source_id, target_id, edge_type, weight, "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db() -> Iterator[sqlite3.Connection]:
    """Yield a fresh in-memory SQLite connection with the migration applied.

    The ``PRAGMA user_version = 1`` line is excluded so individual tests can
    opt into testing it separately.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")

    sql = _MIGRATION_FILE.read_text()
    # Strip the trailing PRAGMA user_version line so the main schema
    # can be executed inside the BEGIN/COMMIT transaction cleanly.
    lines = sql.splitlines()
    filtered = [ln for ln in lines if not ln.strip().upper().startswith("PRAGMA USER_VERSION")]
    conn.executescript("\n".join(filtered))

    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

EXPECTED_TABLES = [
    "projects",
    "edges",
    "tags",
    "project_tags",
    "clusters",
    "project_clusters",
    "node_positions",
    "config",
]


def test_all_tables_created(db: sqlite3.Connection) -> None:
    """All 8 expected tables must exist after running the migration."""
    cur = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = sorted(row[0] for row in cur.fetchall())
    for expected in EXPECTED_TABLES:
        assert expected in tables, f"Table '{expected}' not found. Got: {tables}"


def test_projects_columns(db: sqlite3.Connection) -> None:
    """The projects table must contain all 27 expected columns."""
    cur = db.execute("PRAGMA table_info(projects)")
    columns = {row[1] for row in cur.fetchall()}
    expected_columns = set(_PROJECT_COLUMNS)
    # The schema has 28 columns. The helper dict has exactly 28 keys.
    assert len(expected_columns) == 28, f"Sanity: expected 28 columns in helper, got {len(expected_columns)}"
    missing = expected_columns - columns
    extra = columns - expected_columns
    assert not missing, f"Missing columns in projects table: {missing}"
    assert not extra, f"Unexpected columns in projects table: {extra}"


def test_projects_status_check_constraint(db: sqlite3.Connection) -> None:
    """Valid status values are accepted; invalid ones raise IntegrityError."""
    cur = db.cursor()
    # Valid status should succeed
    _insert_project(cur, id="proj_valid", status="active")
    db.commit()

    # Invalid status should fail
    with pytest.raises(sqlite3.IntegrityError):
        _insert_project(cur, id="proj_invalid", status="invalid", path="/tmp/other")
        db.commit()


def test_edges_unique_constraint(db: sqlite3.Connection) -> None:
    """Duplicate (source_id, target_id, edge_type) raises IntegrityError.

    A different edge_type for the same pair should be allowed.
    """
    cur = db.cursor()
    _insert_project(cur, id="proj_01", path="/tmp/p1")
    _insert_project(cur, id="proj_02", path="/tmp/p2")
    _insert_edge(cur, edge_id="e1", source_id="proj_01", target_id="proj_02", edge_type="manual")
    db.commit()

    # Same pair + type = conflict
    with pytest.raises(sqlite3.IntegrityError):
        _insert_edge(cur, edge_id="e2", source_id="proj_01", target_id="proj_02", edge_type="manual")
        db.commit()

    # Different type = allowed
    db.rollback()
    _insert_edge(cur, edge_id="e3", source_id="proj_01", target_id="proj_02", edge_type="auto_tech")
    db.commit()


def test_edges_type_check_constraint(db: sqlite3.Connection) -> None:
    """Valid edge_type values are accepted; invalid ones raise IntegrityError."""
    cur = db.cursor()
    _insert_project(cur, id="proj_01", path="/tmp/p1")
    _insert_project(cur, id="proj_02", path="/tmp/p2")

    # Valid
    _insert_edge(cur, edge_id="e1", source_id="proj_01", target_id="proj_02", edge_type="manual")
    db.commit()

    # Invalid
    with pytest.raises(sqlite3.IntegrityError):
        _insert_edge(cur, edge_id="e2", source_id="proj_01", target_id="proj_02", edge_type="invalid")
        db.commit()


def test_cascade_delete_edges(db: sqlite3.Connection) -> None:
    """Deleting a project cascades to its edges."""
    cur = db.cursor()
    _insert_project(cur, id="proj_01", path="/tmp/p1")
    _insert_project(cur, id="proj_02", path="/tmp/p2")
    _insert_edge(cur, edge_id="e1", source_id="proj_01", target_id="proj_02")
    db.commit()

    # Sanity: edge exists
    assert cur.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 1

    # Delete source project
    cur.execute("DELETE FROM projects WHERE id = 'proj_01'")
    db.commit()

    assert cur.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0


def test_cascade_delete_project_tags(db: sqlite3.Connection) -> None:
    """Deleting a project or tag cascades to project_tags rows."""
    cur = db.cursor()

    # --- Delete project -> project_tag gone ---
    _insert_project(cur, id="proj_01", path="/tmp/p1")
    _insert_tag(cur, tag_id="tag_01", name="backend")
    cur.execute("INSERT INTO project_tags (project_id, tag_id) VALUES (?, ?)", ("proj_01", "tag_01"))
    db.commit()

    assert cur.execute("SELECT COUNT(*) FROM project_tags").fetchone()[0] == 1
    cur.execute("DELETE FROM projects WHERE id = 'proj_01'")
    db.commit()
    assert cur.execute("SELECT COUNT(*) FROM project_tags").fetchone()[0] == 0

    # --- Delete tag -> project_tag gone ---
    _insert_project(cur, id="proj_02", path="/tmp/p2")
    _insert_tag(cur, tag_id="tag_02", name="frontend")
    cur.execute("INSERT INTO project_tags (project_id, tag_id) VALUES (?, ?)", ("proj_02", "tag_02"))
    db.commit()

    assert cur.execute("SELECT COUNT(*) FROM project_tags").fetchone()[0] == 1
    cur.execute("DELETE FROM tags WHERE id = 'tag_02'")
    db.commit()
    assert cur.execute("SELECT COUNT(*) FROM project_tags").fetchone()[0] == 0


def test_cascade_delete_project_clusters(db: sqlite3.Connection) -> None:
    """Deleting a project or cluster cascades to project_clusters rows."""
    cur = db.cursor()

    # --- Delete project -> project_cluster gone ---
    _insert_project(cur, id="proj_01", path="/tmp/p1")
    _insert_cluster(cur, cluster_id="clus_01", name="web")
    cur.execute("INSERT INTO project_clusters (project_id, cluster_id) VALUES (?, ?)", ("proj_01", "clus_01"))
    db.commit()

    assert cur.execute("SELECT COUNT(*) FROM project_clusters").fetchone()[0] == 1
    cur.execute("DELETE FROM projects WHERE id = 'proj_01'")
    db.commit()
    assert cur.execute("SELECT COUNT(*) FROM project_clusters").fetchone()[0] == 0

    # --- Delete cluster -> project_cluster gone ---
    _insert_project(cur, id="proj_02", path="/tmp/p2")
    _insert_cluster(cur, cluster_id="clus_02", name="mobile")
    cur.execute("INSERT INTO project_clusters (project_id, cluster_id) VALUES (?, ?)", ("proj_02", "clus_02"))
    db.commit()

    assert cur.execute("SELECT COUNT(*) FROM project_clusters").fetchone()[0] == 1
    cur.execute("DELETE FROM clusters WHERE id = 'clus_02'")
    db.commit()
    assert cur.execute("SELECT COUNT(*) FROM project_clusters").fetchone()[0] == 0


def test_cascade_delete_node_positions(db: sqlite3.Connection) -> None:
    """Deleting a project cascades to its node_position row."""
    cur = db.cursor()
    _insert_project(cur, id="proj_01", path="/tmp/p1")
    cur.execute(
        "INSERT INTO node_positions (project_id, x, y, pinned, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("proj_01", 100.0, 200.0, 0, "2025-01-01T00:00:00Z"),
    )
    db.commit()

    assert cur.execute("SELECT COUNT(*) FROM node_positions").fetchone()[0] == 1
    cur.execute("DELETE FROM projects WHERE id = 'proj_01'")
    db.commit()
    assert cur.execute("SELECT COUNT(*) FROM node_positions").fetchone()[0] == 0


def test_default_config_entries(db: sqlite3.Connection) -> None:
    """The migration inserts 4 default config rows with expected keys and values."""
    cur = db.execute("SELECT key, value FROM config ORDER BY key")
    rows = {row[0]: row[1] for row in cur.fetchall()}

    expected = {
        "projects_root": '"~/Documents"',
        "auto_edge_min_weight": "0.3",
        "scan_interval_minutes": "30",
        "sidecar_port": "9721",
    }

    assert set(rows.keys()) == set(expected.keys()), (
        f"Config keys mismatch. Got: {set(rows.keys())}, expected: {set(expected.keys())}"
    )
    for key, expected_value in expected.items():
        assert rows[key] == expected_value, (
            f"Config '{key}': expected {expected_value!r}, got {rows[key]!r}"
        )


def test_tags_name_unique(db: sqlite3.Connection) -> None:
    """Inserting two tags with the same name raises IntegrityError."""
    cur = db.cursor()
    _insert_tag(cur, tag_id="tag_01", name="backend")
    db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        _insert_tag(cur, tag_id="tag_02", name="backend")
        db.commit()


def test_projects_path_unique_but_null_allowed(db: sqlite3.Connection) -> None:
    """Two projects with the same non-null path conflict, but NULL paths are fine."""
    cur = db.cursor()
    _insert_project(cur, id="proj_01", path="/tmp/same")
    db.commit()

    # Duplicate path = IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        _insert_project(cur, id="proj_02", path="/tmp/same")
        db.commit()

    # Two NULL paths = allowed (idea-status projects)
    db.rollback()
    _insert_project(cur, id="proj_03", path=None)
    _insert_project(cur, id="proj_04", path=None)
    db.commit()

    count = cur.execute("SELECT COUNT(*) FROM projects WHERE path IS NULL").fetchone()[0]
    assert count == 2


def test_json_columns_accept_json(db: sqlite3.Connection) -> None:
    """JSON strings stored in languages and frameworks round-trip correctly."""
    cur = db.cursor()
    languages_json = json.dumps({"typescript": 0.65, "css": 0.20, "html": 0.15})
    frameworks_json = json.dumps(["react", "tailwind", "vite"])

    _insert_project(cur, id="proj_json", path="/tmp/json-test", languages=languages_json, frameworks=frameworks_json)
    db.commit()

    row = cur.execute("SELECT languages, frameworks FROM projects WHERE id = 'proj_json'").fetchone()
    assert json.loads(row[0]) == {"typescript": 0.65, "css": 0.20, "html": 0.15}
    assert json.loads(row[1]) == ["react", "tailwind", "vite"]


def test_pragma_user_version(db: sqlite3.Connection) -> None:
    """Running the full migration (including PRAGMA line) sets user_version to 1.

    This test uses a separate connection since the fixture strips the PRAGMA.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")

    sql = _MIGRATION_FILE.read_text()
    conn.executescript(sql)

    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()

    assert version == 1, f"Expected user_version=1, got {version}"
