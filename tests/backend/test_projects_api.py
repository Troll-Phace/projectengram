"""Tests for the FastAPI projects CRUD router.

Covers all five endpoints on ``/api/projects``: list (with filters),
get-by-id, create, partial update, and soft-delete.  Each test class
targets a single responsibility area so failures are easy to localise.

Every test uses an isolated, in-memory-like SQLite database created in
``tmp_path`` with real migrations applied, ensuring schema parity with
production.
"""

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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
from models import Project, ProjectTag, Tag  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "sidecar" / "db" / "migrations"
)
_NOW = "2025-06-01T00:00:00Z"
_ULID_CHARSET = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_env(tmp_path: Path) -> Iterator[tuple[Session, TestClient]]:
    """Create an isolated DB, run migrations, override the session dep.

    Yields:
        A ``(session, client)`` tuple where *session* can be used for
        direct ORM setup (e.g. creating tags) and *client* is a
        ``TestClient`` wired to the FastAPI app with the overridden
        session dependency.
    """
    db_path = tmp_path / "test_projects_api.db"
    migrator = DatabaseMigrator(db_path, _MIGRATIONS_DIR)
    success = migrator.migrate()
    assert success, "Migration failed during test setup"

    engine = get_engine(db_path)

    def _override_get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session

    # Use the same engine for the direct-access session so data written
    # via the ORM is visible to the TestClient (same DB file).
    with Session(engine) as session, TestClient(app) as client:
        yield session, client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_project(client: TestClient, **overrides: Any) -> dict[str, Any]:
    """POST a new project and return the JSON response body.

    Provides a default ``name`` of ``"test-proj"`` which can be
    overridden via keyword arguments.
    """
    payload: dict[str, Any] = {"name": "test-proj"}
    payload.update(overrides)
    resp = client.post("/api/projects", json=payload)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    return resp.json()


# ===========================================================================
# Test classes
# ===========================================================================


class TestProjectCreate:
    """POST /api/projects — creation endpoint."""

    def test_create_project_minimal(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Minimal payload returns 201 with ULID id and sensible defaults."""
        _, client = api_env
        data = _create_project(client)

        # ULID: 26-char Crockford Base32
        assert len(data["id"]) == 26
        assert set(data["id"]).issubset(_ULID_CHARSET)

        # Timestamps populated
        assert data["created_at"] is not None
        assert data["updated_at"] is not None

        # Defaults
        assert data["status"] == "active"
        assert data["git_dirty"] is False
        assert data["missing"] is False

    def test_create_project_all_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """All user-settable fields round-trip correctly."""
        _, client = api_env
        payload = {
            "name": "full-project",
            "path": "/tmp/full-project",
            "description": "A fully populated project",
            "status": "paused",
            "primary_language": "python",
            "languages": '{"python": 0.8, "sql": 0.2}',
            "frameworks": '["fastapi", "sqlmodel"]',
            "package_manager": "pip",
            "git_remote_url": "https://github.com/test/repo",
            "git_branch": "main",
            "color_override": "#FF5500",
            "icon_override": "brain",
            "notes": "Important project",
        }
        data = _create_project(client, **payload)

        for key, value in payload.items():
            assert data[key] == value, f"Mismatch on '{key}': {data[key]!r} != {value!r}"

    def test_create_project_idea(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Status 'idea' is accepted and path can be None."""
        _, client = api_env
        data = _create_project(client, name="idea", status="idea")

        assert data["status"] == "idea"
        assert data["path"] is None

    def test_create_project_duplicate_path(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Second project with the same path returns 409."""
        _, client = api_env
        _create_project(client, name="first", path="/tmp/same")

        resp = client.post(
            "/api/projects",
            json={"name": "second", "path": "/tmp/same"},
        )
        assert resp.status_code == 409
        assert "path" in resp.json()["detail"].lower()

    def test_create_project_null_paths_coexist(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Multiple projects with no path do not trigger a unique conflict."""
        _, client = api_env
        data1 = _create_project(client, name="idea-one")
        data2 = _create_project(client, name="idea-two")

        assert data1["id"] != data2["id"]
        assert data1["path"] is None
        assert data2["path"] is None

    def test_create_project_invalid_status(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """An invalid status value returns 422."""
        _, client = api_env
        resp = client.post(
            "/api/projects",
            json={"name": "bad", "status": "invalid"},
        )
        assert resp.status_code == 422

    def test_create_project_missing_name(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Omitting the required name field returns 422."""
        _, client = api_env
        resp = client.post("/api/projects", json={})
        assert resp.status_code == 422


class TestProjectRead:
    """GET /api/projects and GET /api/projects/{id}."""

    def test_list_projects_empty(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Empty database returns an empty list."""
        _, client = api_env
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_projects_returns_all(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """All created projects appear in the list."""
        _, client = api_env
        for name in ("alpha", "beta", "gamma"):
            _create_project(client, name=name, path=f"/tmp/{name}")

        resp = client.get("/api/projects")
        assert resp.status_code == 200
        names = {p["name"] for p in resp.json()}
        assert names == {"alpha", "beta", "gamma"}

    def test_list_projects_excludes_deleted(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Soft-deleted projects are excluded from the list endpoint."""
        _, client = api_env
        p1 = _create_project(client, name="keep-me", path="/tmp/keep")
        p2 = _create_project(client, name="delete-me", path="/tmp/delete")

        client.delete(f"/api/projects/{p2['id']}")

        resp = client.get("/api/projects")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()]
        assert p1["id"] in ids
        assert p2["id"] not in ids

    def test_get_project_by_id(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Retrieve a single project by its ULID."""
        _, client = api_env
        created = _create_project(client, name="look-me-up", path="/tmp/lookup")

        resp = client.get(f"/api/projects/{created['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == created["id"]
        assert data["name"] == "look-me-up"

    def test_get_project_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A non-existent ID returns 404."""
        _, client = api_env
        resp = client.get("/api/projects/00000000000000000000000000")
        assert resp.status_code == 404


class TestProjectFilter:
    """GET /api/projects?status=...&language=...&tag=... query filters."""

    def test_filter_by_status(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Only projects matching the status filter are returned."""
        _, client = api_env
        _create_project(client, name="active-proj", status="active", path="/tmp/a")
        _create_project(client, name="paused-proj", status="paused", path="/tmp/b")
        _create_project(client, name="archived-proj", status="archived", path="/tmp/c")

        resp = client.get("/api/projects", params={"status": "paused"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["name"] == "paused-proj"

    def test_filter_by_language(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Only projects matching the primary_language filter are returned."""
        _, client = api_env
        _create_project(
            client, name="py-proj", primary_language="python", path="/tmp/py"
        )
        _create_project(
            client, name="ts-proj", primary_language="typescript", path="/tmp/ts"
        )
        _create_project(
            client, name="rs-proj", primary_language="rust", path="/tmp/rs"
        )

        resp = client.get("/api/projects", params={"language": "python"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["name"] == "py-proj"

    def test_filter_by_tag(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Projects linked to a tag are returned when filtered by tag name."""
        session, client = api_env
        proj = _create_project(client, name="tagged-proj", path="/tmp/tagged")

        # Create a tag and link it via direct ORM access
        tag = Tag(name="backend", color="#FF0000", created_at=_NOW)
        session.add(tag)
        session.commit()
        session.refresh(tag)

        link = ProjectTag(project_id=proj["id"], tag_id=tag.id)
        session.add(link)
        session.commit()

        # Also create an untagged project
        _create_project(client, name="untagged-proj", path="/tmp/untagged")

        resp = client.get("/api/projects", params={"tag": "backend"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["name"] == "tagged-proj"

    def test_filter_by_tag_no_match(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A tag filter with no matching projects returns an empty list."""
        _, client = api_env
        _create_project(client, name="lonely-proj", path="/tmp/lonely")

        resp = client.get("/api/projects", params={"tag": "nonexistent"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_filter_combined(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Combined status and language filters return the intersection."""
        _, client = api_env
        _create_project(
            client,
            name="active-py",
            status="active",
            primary_language="python",
            path="/tmp/apy",
        )
        _create_project(
            client,
            name="paused-py",
            status="paused",
            primary_language="python",
            path="/tmp/ppy",
        )
        _create_project(
            client,
            name="active-ts",
            status="active",
            primary_language="typescript",
            path="/tmp/ats",
        )

        resp = client.get(
            "/api/projects",
            params={"status": "active", "language": "python"},
        )
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["name"] == "active-py"


class TestProjectUpdate:
    """PATCH /api/projects/{id} — partial update endpoint."""

    def test_update_name(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with a new name updates only the name."""
        _, client = api_env
        proj = _create_project(client, name="old-name", path="/tmp/upd-name")

        resp = client.patch(
            f"/api/projects/{proj['id']}",
            json={"name": "new-name"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "new-name"

    def test_update_multiple_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with several fields updates them all."""
        _, client = api_env
        proj = _create_project(client, name="multi-upd", path="/tmp/multi-upd")

        resp = client.patch(
            f"/api/projects/{proj['id']}",
            json={
                "name": "renamed",
                "status": "paused",
                "description": "now paused",
                "primary_language": "rust",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "renamed"
        assert data["status"] == "paused"
        assert data["description"] == "now paused"
        assert data["primary_language"] == "rust"

    def test_update_sets_updated_at(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH refreshes the updated_at timestamp."""
        _, client = api_env
        proj = _create_project(client, name="ts-check", path="/tmp/ts-check")
        original_updated = proj["updated_at"]

        resp = client.patch(
            f"/api/projects/{proj['id']}",
            json={"notes": "touched"},
        )
        assert resp.status_code == 200
        # updated_at should differ (or at least be re-set)
        new_updated = resp.json()["updated_at"]
        assert new_updated >= original_updated

    def test_update_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH on a non-existent ID returns 404."""
        _, client = api_env
        resp = client.patch(
            "/api/projects/00000000000000000000000000",
            json={"name": "ghost"},
        )
        assert resp.status_code == 404

    def test_update_invalid_status(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with an invalid status value returns 422."""
        _, client = api_env
        proj = _create_project(client, name="bad-upd", path="/tmp/bad-upd")

        resp = client.patch(
            f"/api/projects/{proj['id']}",
            json={"status": "bad"},
        )
        assert resp.status_code == 422

    def test_update_duplicate_path(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH that causes a path collision returns 409."""
        _, client = api_env
        proj_a = _create_project(client, name="proj-a", path="/tmp/path-a")
        proj_b = _create_project(client, name="proj-b", path="/tmp/path-b")

        resp = client.patch(
            f"/api/projects/{proj_b['id']}",
            json={"path": proj_a["path"]},
        )
        assert resp.status_code == 409

    def test_partial_update_preserves_other_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH on one field leaves unrelated fields unchanged."""
        _, client = api_env
        proj = _create_project(
            client,
            name="preserve-me",
            path="/tmp/preserve",
            description="original description",
            primary_language="go",
            notes="some notes",
        )

        resp = client.patch(
            f"/api/projects/{proj['id']}",
            json={"name": "changed-name"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "changed-name"
        assert data["description"] == "original description"
        assert data["primary_language"] == "go"
        assert data["notes"] == "some notes"
        assert data["path"] == "/tmp/preserve"


class TestProjectDelete:
    """DELETE /api/projects/{id} — soft-delete endpoint."""

    def test_delete_sets_deleted_at(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Soft-delete sets deleted_at and refreshes updated_at."""
        _, client = api_env
        proj = _create_project(client, name="to-delete", path="/tmp/del")
        original_updated = proj["updated_at"]

        resp = client.delete(f"/api/projects/{proj['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted_at"] is not None
        assert data["updated_at"] >= original_updated

    def test_delete_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """DELETE on a non-existent ID returns 404."""
        _, client = api_env
        resp = client.delete("/api/projects/00000000000000000000000000")
        assert resp.status_code == 404

    def test_delete_idempotent(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Deleting the same project twice returns 200 both times."""
        _, client = api_env
        proj = _create_project(client, name="double-del", path="/tmp/double")

        resp1 = client.delete(f"/api/projects/{proj['id']}")
        assert resp1.status_code == 200

        resp2 = client.delete(f"/api/projects/{proj['id']}")
        assert resp2.status_code == 200

    def test_deleted_excluded_from_list(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A soft-deleted project does not appear in the list endpoint."""
        _, client = api_env
        proj = _create_project(client, name="vanish", path="/tmp/vanish")
        client.delete(f"/api/projects/{proj['id']}")

        resp = client.get("/api/projects")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()]
        assert proj["id"] not in ids

    def test_deleted_still_accessible_by_id(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A soft-deleted project is still returned by the get-by-id endpoint."""
        _, client = api_env
        proj = _create_project(client, name="still-here", path="/tmp/still")
        client.delete(f"/api/projects/{proj['id']}")

        resp = client.get(f"/api/projects/{proj['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted_at"] is not None
        assert data["name"] == "still-here"


class TestResponseShape:
    """Verify the JSON shape returned by the projects endpoints."""

    def test_response_excludes_relationships(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Response JSON contains data columns but not ORM relationships."""
        _, client = api_env
        proj = _create_project(
            client,
            name="shape-check",
            path="/tmp/shape",
            description="testing shape",
            primary_language="python",
        )

        resp = client.get(f"/api/projects/{proj['id']}")
        assert resp.status_code == 200
        data = resp.json()

        # Relationship keys must NOT be present
        forbidden_keys = {
            "source_edges",
            "target_edges",
            "tag_links",
            "cluster_links",
            "node_position",
        }
        for key in forbidden_keys:
            assert key not in data, f"Unexpected relationship key '{key}' in response"

        # All expected data columns MUST be present
        expected_keys = {
            "id",
            "name",
            "path",
            "description",
            "status",
            "primary_language",
            "languages",
            "frameworks",
            "package_manager",
            "loc",
            "file_count",
            "size_bytes",
            "git_remote_url",
            "git_branch",
            "git_dirty",
            "git_last_commit_hash",
            "git_last_commit_date",
            "git_last_commit_msg",
            "git_branch_count",
            "color_override",
            "icon_override",
            "notes",
            "missing",
            "deleted_at",
            "last_scanned_at",
            "last_opened_at",
            "created_at",
            "updated_at",
        }
        actual_keys = set(data.keys())
        missing = expected_keys - actual_keys
        assert not missing, f"Missing expected keys: {missing}"
