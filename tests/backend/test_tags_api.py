"""Tests for the FastAPI tags CRUD and project-tag assignment routers.

Covers all six endpoints across ``/api/tags`` (list, create, update,
hard-delete) and ``/api/projects/{id}/tags`` (assign, remove).  Each
test class targets a single responsibility area so failures are easy to
localise.

Every test uses an isolated SQLite database created in ``tmp_path``
with real migrations applied, ensuring schema parity with production.
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
_ULID_CHARSET = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_env(tmp_path: Path) -> Iterator[tuple[Session, TestClient]]:
    """Create an isolated DB, run migrations, override the session dep.

    Yields:
        A ``(session, client)`` tuple where *session* can be used for
        direct ORM verification and *client* is a ``TestClient`` wired
        to the FastAPI app with the overridden session dependency.
    """
    db_path = tmp_path / "test_tags_api.db"
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_tag(client: TestClient, **overrides: Any) -> dict[str, Any]:
    """POST a new tag and return the JSON response body.

    Provides a default ``name`` of ``"test-tag"`` which can be
    overridden via keyword arguments.
    """
    payload: dict[str, Any] = {"name": "test-tag"}
    payload.update(overrides)
    resp = client.post("/api/tags", json=payload)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    return resp.json()


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


class TestTagCreate:
    """POST /api/tags -- creation endpoint."""

    def test_create_tag_minimal(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Minimal payload (name only) returns 201 with ULID id and timestamp."""
        _, client = api_env
        data = _create_tag(client)

        # ULID: 26-char Crockford Base32
        assert len(data["id"]) == 26
        assert set(data["id"]).issubset(_ULID_CHARSET)

        # Timestamp populated
        assert data["created_at"] is not None

        # Name is set, color defaults to None
        assert data["name"] == "test-tag"
        assert data["color"] is None

    def test_create_tag_with_color(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Providing both name and color stores both correctly."""
        _, client = api_env
        data = _create_tag(client, name="frontend", color="#3B82F6")

        assert data["name"] == "frontend"
        assert data["color"] == "#3B82F6"

    def test_create_tag_duplicate_name(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Second tag with the same name returns 409."""
        _, client = api_env
        _create_tag(client, name="duplicate")

        resp = client.post("/api/tags", json={"name": "duplicate"})
        assert resp.status_code == 409
        assert "name" in resp.json()["detail"].lower()

    def test_create_tag_missing_name(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Omitting the required name field returns 422."""
        _, client = api_env
        resp = client.post("/api/tags", json={})
        assert resp.status_code == 422


class TestTagRead:
    """GET /api/tags -- list endpoint."""

    def test_list_tags_empty(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Empty database returns an empty list."""
        _, client = api_env
        resp = client.get("/api/tags")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_tags_returns_all(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """All created tags appear in the list."""
        _, client = api_env
        for name in ("backend", "frontend", "devops"):
            _create_tag(client, name=name)

        resp = client.get("/api/tags")
        assert resp.status_code == 200
        names = {t["name"] for t in resp.json()}
        assert names == {"backend", "frontend", "devops"}


class TestTagUpdate:
    """PATCH /api/tags/{id} -- partial update endpoint."""

    def test_update_name(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with a new name updates only the name."""
        _, client = api_env
        tag = _create_tag(client, name="old-name")

        resp = client.patch(
            f"/api/tags/{tag['id']}",
            json={"name": "new-name"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "new-name"
        # Color unchanged
        assert resp.json()["color"] == tag["color"]

    def test_update_color(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with a new color updates the color and preserves the name."""
        _, client = api_env
        tag = _create_tag(client, name="colorful", color="#FF0000")

        resp = client.patch(
            f"/api/tags/{tag['id']}",
            json={"color": "#00FF00"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["color"] == "#00FF00"
        assert data["name"] == "colorful"

    def test_update_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH on a non-existent ID returns 404."""
        _, client = api_env
        resp = client.patch(
            "/api/tags/00000000000000000000000000",
            json={"name": "ghost"},
        )
        assert resp.status_code == 404

    def test_update_duplicate_name(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH that causes a name collision returns 409."""
        _, client = api_env
        _create_tag(client, name="existing-tag")
        tag_b = _create_tag(client, name="rename-me")

        resp = client.patch(
            f"/api/tags/{tag_b['id']}",
            json={"name": "existing-tag"},
        )
        assert resp.status_code == 409
        assert "name" in resp.json()["detail"].lower()


class TestTagDelete:
    """DELETE /api/tags/{id} -- hard-delete endpoint."""

    def test_delete_tag(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Deleting an existing tag returns 200 with {"ok": true}."""
        _, client = api_env
        tag = _create_tag(client, name="to-delete")

        resp = client.delete(f"/api/tags/{tag['id']}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Verify tag is actually gone from list
        list_resp = client.get("/api/tags")
        assert list_resp.status_code == 200
        ids = [t["id"] for t in list_resp.json()]
        assert tag["id"] not in ids

    def test_delete_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """DELETE on a non-existent ID returns 404."""
        _, client = api_env
        resp = client.delete("/api/tags/00000000000000000000000000")
        assert resp.status_code == 404

    def test_delete_cascades_project_tags(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Deleting a tag removes associated ProjectTag join rows via cascade.

        Uses the ORM session to verify the join table directly, since
        the API does not expose project_tags as a resource.
        """
        session, client = api_env

        # Create a project and a tag, then assign the tag
        proj = _create_project(client, name="cascade-proj", path="/tmp/cascade")
        tag = _create_tag(client, name="cascade-tag")
        assign_resp = client.post(
            f"/api/projects/{proj['id']}/tags",
            json={"tag_id": tag["id"]},
        )
        assert assign_resp.status_code == 201

        # Verify the link exists in the database via ORM
        link = session.exec(
            select(ProjectTag).where(
                ProjectTag.project_id == proj["id"],
                ProjectTag.tag_id == tag["id"],
            )
        ).first()
        assert link is not None

        # Delete the tag
        del_resp = client.delete(f"/api/tags/{tag['id']}")
        assert del_resp.status_code == 200

        # Verify the ProjectTag row was cascaded away
        session.expire_all()
        orphan = session.exec(
            select(ProjectTag).where(
                ProjectTag.project_id == proj["id"],
                ProjectTag.tag_id == tag["id"],
            )
        ).first()
        assert orphan is None


class TestTagAssignment:
    """POST/DELETE /api/projects/{id}/tags -- tag assignment endpoints."""

    def test_assign_tag_to_project(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Assigning a tag returns 201 with the tag data."""
        _, client = api_env
        proj = _create_project(client, name="tagged-proj", path="/tmp/tagged")
        tag = _create_tag(client, name="my-tag")

        resp = client.post(
            f"/api/projects/{proj['id']}/tags",
            json={"tag_id": tag["id"]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == tag["id"]
        assert data["name"] == "my-tag"

    def test_assign_tag_project_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Assigning a tag to a non-existent project returns 404."""
        _, client = api_env
        tag = _create_tag(client, name="orphan-tag")

        resp = client.post(
            "/api/projects/00000000000000000000000000/tags",
            json={"tag_id": tag["id"]},
        )
        assert resp.status_code == 404
        assert "project" in resp.json()["detail"].lower()

    def test_assign_tag_tag_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Assigning a non-existent tag returns 404."""
        _, client = api_env
        proj = _create_project(client, name="waiting-proj", path="/tmp/waiting")

        resp = client.post(
            f"/api/projects/{proj['id']}/tags",
            json={"tag_id": "00000000000000000000000000"},
        )
        assert resp.status_code == 404
        assert "tag" in resp.json()["detail"].lower()

    def test_assign_tag_duplicate(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Assigning the same tag twice returns 409."""
        _, client = api_env
        proj = _create_project(client, name="dup-assign", path="/tmp/dup-assign")
        tag = _create_tag(client, name="dup-tag")

        # First assignment succeeds
        resp1 = client.post(
            f"/api/projects/{proj['id']}/tags",
            json={"tag_id": tag["id"]},
        )
        assert resp1.status_code == 201

        # Second assignment conflicts
        resp2 = client.post(
            f"/api/projects/{proj['id']}/tags",
            json={"tag_id": tag["id"]},
        )
        assert resp2.status_code == 409
        assert "already assigned" in resp2.json()["detail"].lower()

    def test_remove_tag_from_project(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Removing an assigned tag returns 200 with {"ok": true}."""
        _, client = api_env
        proj = _create_project(client, name="unlink-proj", path="/tmp/unlink")
        tag = _create_tag(client, name="unlink-tag")

        # Assign first
        client.post(
            f"/api/projects/{proj['id']}/tags",
            json={"tag_id": tag["id"]},
        )

        # Remove
        resp = client.delete(
            f"/api/projects/{proj['id']}/tags/{tag['id']}"
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_remove_tag_not_assigned(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Removing a tag that is not assigned returns 404."""
        _, client = api_env
        proj = _create_project(client, name="no-link-proj", path="/tmp/no-link")
        tag = _create_tag(client, name="no-link-tag")

        resp = client.delete(
            f"/api/projects/{proj['id']}/tags/{tag['id']}"
        )
        assert resp.status_code == 404
        assert "not assigned" in resp.json()["detail"].lower()


class TestTagResponseShape:
    """Verify the JSON shape returned by the tags endpoints."""

    def test_response_contains_all_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Response JSON contains all expected TagPublic fields."""
        _, client = api_env
        tag = _create_tag(client, name="shape-tag", color="#AABBCC")

        resp = client.get("/api/tags")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

        tag_data = data[0]
        expected_keys = {"id", "name", "color", "created_at"}
        actual_keys = set(tag_data.keys())
        missing = expected_keys - actual_keys
        assert not missing, f"Missing expected keys: {missing}"

    def test_response_excludes_relationships(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Response JSON does not contain ORM relationship keys."""
        _, client = api_env
        tag = _create_tag(client, name="no-rels")

        resp = client.get("/api/tags")
        assert resp.status_code == 200
        tag_data = resp.json()[0]

        forbidden_keys = {"project_links"}
        for key in forbidden_keys:
            assert key not in tag_data, (
                f"Unexpected relationship key '{key}' in response"
            )
