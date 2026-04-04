"""Tests for the FastAPI scan router.

Covers all three endpoints on ``/api/scan``: status check, full discovery
scan, and the single-project scan stub.  Each test class targets a single
responsibility area so failures are easy to localise.

The ``api_env_with_projects`` fixture creates an isolated SQLite database
with real migrations, a temporary directory tree simulating a projects
root, and a seeded ``projects_root`` config entry pointing to that tree.
This ensures complete isolation from the host filesystem.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session, select
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# sys.path setup — mirrors conftest.py convention
# ---------------------------------------------------------------------------

_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from db.engine import get_engine  # noqa: E402
from db.migrations.migrator import DatabaseMigrator  # noqa: E402
from db.session import get_session  # noqa: E402
from main import app  # noqa: E402
from models import Config, Project  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "sidecar" / "db" / "migrations"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_project(
    session: Session,
    *,
    name: str,
    path: str | None = None,
    **overrides: object,
) -> Project:
    """Insert a project into the database via the ORM.

    Returns:
        The refreshed ``Project`` instance with server-generated defaults.
    """
    now = _now_iso()
    project = Project(
        name=name, path=path, created_at=now, updated_at=now, **overrides
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_env(tmp_path: Path) -> Iterator[tuple[Session, TestClient]]:
    """Create an isolated DB and run migrations without directory setup.

    This simpler fixture is used by tests that need to manipulate the
    config table directly (e.g. to test missing/empty config values).

    Yields:
        A ``(session, client)`` tuple.
    """
    db_path = tmp_path / "test_scan_api.db"
    migrator = DatabaseMigrator(db_path, _MIGRATIONS_DIR)
    success = migrator.migrate()
    assert success, "Migration failed during test setup"

    engine = get_engine(db_path)

    def _override_get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session

    with Session(engine) as session, TestClient(app) as client:
        yield session, client

    app.dependency_overrides.clear()


@pytest.fixture()
def api_env_with_projects(
    tmp_path: Path,
) -> Iterator[tuple[Session, TestClient, Path]]:
    """Create an isolated DB + temp project directories.

    Sets up:
    - A fresh migrated DB with session override
    - A temp directory with project subdirectories:
      ``proj-a/``, ``proj-b/``, ``proj-c/``, ``.hidden/``
    - The config table's ``projects_root`` pointing to the temp directory

    Yields:
        ``(session, client, projects_root_path)``
    """
    # 1. Create temp DB + run migrations
    db_path = tmp_path / "test_scan_api.db"
    migrator = DatabaseMigrator(db_path, _MIGRATIONS_DIR)
    success = migrator.migrate()
    assert success, "Migration failed during test setup"

    engine = get_engine(db_path)

    def _override_get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session

    # 2. Create temp project directories
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    (projects_root / "proj-a").mkdir()
    (projects_root / "proj-b").mkdir()
    (projects_root / "proj-c").mkdir()
    (projects_root / ".hidden").mkdir()

    # 3. Set projects_root in config table
    with Session(engine) as setup_session:
        config_entry = setup_session.get(Config, "projects_root")
        assert config_entry is not None, "Migration must seed projects_root config"
        config_entry.value = json.dumps(str(projects_root))
        config_entry.updated_at = _now_iso()
        setup_session.add(config_entry)
        setup_session.commit()

    # 4. Yield
    with Session(engine) as session, TestClient(app) as client:
        yield session, client, projects_root

    app.dependency_overrides.clear()


# ===========================================================================
# Test classes
# ===========================================================================


class TestScanStatus:
    """GET /api/scan/status — scan status endpoint."""

    def test_status_returns_valid_response(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """The status endpoint returns a well-formed response.

        The lifespan fires a background full scan on startup, so the
        status may be ``"idle"`` or ``"scanning"`` depending on timing.
        We validate the response shape and allowed values rather than
        asserting a specific state.
        """
        _, client = api_env
        resp = client.get("/api/scan/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("idle", "scanning")
        assert "progress" in data
        assert "phase" in data
        assert "total" in data
        assert "completed" in data


class TestScanFull:
    """POST /api/scan/full — full discovery scan endpoint."""

    def test_discovers_new_directories(
        self,
        api_env_with_projects: tuple[Session, TestClient, Path],
    ) -> None:
        """Directories on disk with no matching DB projects appear as new."""
        _, client, projects_root = api_env_with_projects

        resp = client.post("/api/scan/full")
        assert resp.status_code == 200

        data = resp.json()
        new_names = {d["name"] for d in data["new"]}
        assert new_names == {"proj-a", "proj-b", "proj-c"}
        assert len(data["missing"]) == 0
        assert data["existing_count"] == 0

    def test_detects_missing_projects(
        self,
        api_env_with_projects: tuple[Session, TestClient, Path],
    ) -> None:
        """A DB project whose directory no longer exists appears as missing."""
        session, client, projects_root = api_env_with_projects

        _make_project(
            session,
            name="deleted-project",
            path=str(projects_root / "deleted-project"),
        )

        resp = client.post("/api/scan/full")
        assert resp.status_code == 200

        data = resp.json()
        missing_names = {m["name"] for m in data["missing"]}
        assert "deleted-project" in missing_names

    def test_identifies_existing_projects(
        self,
        api_env_with_projects: tuple[Session, TestClient, Path],
    ) -> None:
        """A DB project whose directory exists on disk counts as existing."""
        session, client, projects_root = api_env_with_projects

        _make_project(
            session,
            name="proj-a",
            path=str(projects_root / "proj-a"),
        )

        resp = client.post("/api/scan/full")
        assert resp.status_code == 200

        data = resp.json()
        assert data["existing_count"] == 1
        # proj-a should NOT appear in new since it is known
        new_names = {d["name"] for d in data["new"]}
        assert "proj-a" not in new_names

    def test_sets_missing_flag_in_db(
        self,
        api_env_with_projects: tuple[Session, TestClient, Path],
    ) -> None:
        """The scan sets missing=True on projects whose dirs are gone."""
        session, client, projects_root = api_env_with_projects

        project = _make_project(
            session,
            name="vanished",
            path=str(projects_root / "vanished"),
        )
        project_id = project.id

        resp = client.post("/api/scan/full")
        assert resp.status_code == 200

        # The test session and API endpoint session are separate objects backed
        # by the same SQLite file. expire_all() forces a fresh read after the
        # API endpoint committed its changes.
        session.expire_all()
        db_project = session.get(Project, project_id)
        assert db_project is not None
        assert db_project.missing is True

    def test_clears_missing_flag_when_reappears(
        self,
        api_env_with_projects: tuple[Session, TestClient, Path],
    ) -> None:
        """The scan clears missing=False when a project dir reappears."""
        session, client, projects_root = api_env_with_projects

        project = _make_project(
            session,
            name="proj-a",
            path=str(projects_root / "proj-a"),
            missing=True,
        )
        project_id = project.id

        resp = client.post("/api/scan/full")
        assert resp.status_code == 200

        # Re-read from DB after the API committed its changes
        session.expire_all()
        db_project = session.get(Project, project_id)
        assert db_project is not None
        assert db_project.missing is False

    def test_does_not_auto_add_new_projects(
        self,
        api_env_with_projects: tuple[Session, TestClient, Path],
    ) -> None:
        """New directories are reported but not inserted into the DB."""
        session, client, _ = api_env_with_projects

        resp = client.post("/api/scan/full")
        assert resp.status_code == 200

        data = resp.json()
        # There should be new directories reported
        assert len(data["new"]) > 0

        # But no projects should exist in the database
        session.expire_all()
        all_projects = session.exec(select(Project)).all()
        assert len(all_projects) == 0

    def test_excludes_hidden_directories(
        self,
        api_env_with_projects: tuple[Session, TestClient, Path],
    ) -> None:
        """Hidden directories (starting with dot) do not appear as new."""
        _, client, _ = api_env_with_projects

        resp = client.post("/api/scan/full")
        assert resp.status_code == 200

        data = resp.json()
        new_names = {d["name"] for d in data["new"]}
        assert ".hidden" not in new_names

    def test_returns_422_when_config_not_set(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A missing or null projects_root config triggers 422."""
        session, client = api_env

        # Set the config value to null
        config_entry = session.get(Config, "projects_root")
        assert config_entry is not None
        config_entry.value = None
        config_entry.updated_at = _now_iso()
        session.add(config_entry)
        session.commit()

        resp = client.post("/api/scan/full")
        assert resp.status_code == 422

    def test_returns_422_when_directory_missing(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A projects_root pointing to a nonexistent directory triggers 422."""
        session, client = api_env

        # Point to a path that does not exist on disk
        config_entry = session.get(Config, "projects_root")
        assert config_entry is not None
        config_entry.value = json.dumps("/tmp/absolutely_nonexistent_path_12345")
        config_entry.updated_at = _now_iso()
        session.add(config_entry)
        session.commit()

        resp = client.post("/api/scan/full")
        assert resp.status_code == 422

    def test_mixed_scenario(
        self,
        api_env_with_projects: tuple[Session, TestClient, Path],
    ) -> None:
        """A realistic scenario with existing, missing, and new projects."""
        session, client, projects_root = api_env_with_projects

        # proj-a exists on disk and is known in DB
        _make_project(
            session,
            name="proj-a",
            path=str(projects_root / "proj-a"),
        )
        # proj-deleted is known in DB but NOT on disk
        _make_project(
            session,
            name="proj-deleted",
            path=str(projects_root / "proj-deleted"),
        )

        resp = client.post("/api/scan/full")
        assert resp.status_code == 200

        data = resp.json()
        new_names = {d["name"] for d in data["new"]}
        missing_names = {m["name"] for m in data["missing"]}

        assert "proj-b" in new_names
        assert "proj-c" in new_names
        assert "proj-deleted" in missing_names
        assert data["existing_count"] == 1

    def test_projects_root_in_response(
        self,
        api_env_with_projects: tuple[Session, TestClient, Path],
    ) -> None:
        """The response includes a resolved absolute projects_root path."""
        _, client, projects_root = api_env_with_projects

        resp = client.post("/api/scan/full")
        assert resp.status_code == 200

        data = resp.json()
        response_root = data["projects_root"]
        assert Path(response_root).is_absolute()
        assert response_root == str(projects_root.resolve())


class TestScanProject:
    """POST /api/scan/project/{project_id} — single project scan."""

    def test_returns_404_for_unknown_project(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A non-existent project ID returns 404."""
        _, client = api_env
        resp = client.post("/api/scan/project/nonexistent-id")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Project not found."

    def test_returns_422_for_project_without_path(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A project with no path returns 422."""
        session, client = api_env
        project = _make_project(session, name="no-path-project", path=None)

        resp = client.post(f"/api/scan/project/{project.id}")

        assert resp.status_code == 422
        assert resp.json()["detail"] == "Project has no path."

    def test_returns_202_for_valid_project(
        self,
        api_env_with_projects: tuple[Session, TestClient, Path],
    ) -> None:
        """A valid project with a path returns 202 Accepted."""
        session, client, projects_root = api_env_with_projects
        project = _make_project(
            session,
            name="proj-a",
            path=str(projects_root / "proj-a"),
        )

        resp = client.post(f"/api/scan/project/{project.id}")

        assert resp.status_code == 202
        data = resp.json()
        assert data["detail"] == "Scan queued."
        assert data["project_id"] == project.id
