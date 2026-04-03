"""Tests for the FastAPI clusters CRUD and membership router.

Covers all six endpoints on ``/api/clusters``: list, create, partial
update, hard-delete, add-project-to-cluster, and remove-project-from-
cluster.  Each test class targets a single responsibility area so
failures are easy to localise.

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
from models import Cluster, Project, ProjectCluster  # noqa: E402

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
        direct ORM verification (e.g. checking ``ProjectCluster`` rows)
        and *client* is a ``TestClient`` wired to the FastAPI app with
        the overridden session dependency.
    """
    db_path = tmp_path / "test_clusters_api.db"
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


def _create_cluster(client: TestClient, **overrides: Any) -> dict[str, Any]:
    """POST a new cluster and return the JSON response body.

    Provides a default ``name`` of ``"test-cluster"`` which can be
    overridden via keyword arguments.
    """
    payload: dict[str, Any] = {"name": "test-cluster"}
    payload.update(overrides)
    resp = client.post("/api/clusters", json=payload)
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


class TestClusterCreate:
    """POST /api/clusters -- creation endpoint."""

    def test_create_cluster_minimal(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Minimal payload (name only) returns 201 with sensible defaults."""
        _, client = api_env
        data = _create_cluster(client)

        # ULID: 26-char Crockford Base32
        assert len(data["id"]) == 26
        assert set(data["id"]).issubset(_ULID_CHARSET)

        # Timestamps populated
        assert data["created_at"] is not None
        assert data["updated_at"] is not None

        # Defaults
        assert data["name"] == "test-cluster"
        assert data["color"] is None
        assert data["opacity"] == 0.15
        assert data["collapsed"] is False

    def test_create_cluster_all_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """All user-settable fields round-trip correctly."""
        _, client = api_env
        payload = {
            "name": "frontend-group",
            "color": "#3B82F6",
            "opacity": 0.8,
            "collapsed": True,
        }
        data = _create_cluster(client, **payload)

        for key, value in payload.items():
            assert data[key] == value, f"Mismatch on '{key}': {data[key]!r} != {value!r}"

    def test_create_cluster_missing_name(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Omitting the required name field returns 422."""
        _, client = api_env
        resp = client.post("/api/clusters", json={})
        assert resp.status_code == 422

    def test_create_cluster_invalid_opacity_below_zero(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """An opacity below 0.0 returns 422."""
        _, client = api_env
        resp = client.post(
            "/api/clusters",
            json={"name": "bad-opacity", "opacity": -0.1},
        )
        assert resp.status_code == 422

    def test_create_cluster_invalid_opacity_above_one(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """An opacity above 1.0 returns 422."""
        _, client = api_env
        resp = client.post(
            "/api/clusters",
            json={"name": "bad-opacity", "opacity": 1.5},
        )
        assert resp.status_code == 422


class TestClusterRead:
    """GET /api/clusters -- list endpoint."""

    def test_list_clusters_empty(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Empty database returns an empty list."""
        _, client = api_env
        resp = client.get("/api/clusters")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_clusters_returns_all(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """All created clusters appear in the list."""
        _, client = api_env
        for name in ("alpha", "beta", "gamma"):
            _create_cluster(client, name=name)

        resp = client.get("/api/clusters")
        assert resp.status_code == 200
        names = {c["name"] for c in resp.json()}
        assert names == {"alpha", "beta", "gamma"}


class TestClusterUpdate:
    """PATCH /api/clusters/{id} -- partial update endpoint."""

    def test_update_name(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with a new name updates only the name."""
        _, client = api_env
        cluster = _create_cluster(client, name="old-name")

        resp = client.patch(
            f"/api/clusters/{cluster['id']}",
            json={"name": "new-name"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "new-name"

    def test_update_opacity(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with a new opacity updates the value."""
        _, client = api_env
        cluster = _create_cluster(client, name="opacity-test")

        resp = client.patch(
            f"/api/clusters/{cluster['id']}",
            json={"opacity": 0.75},
        )
        assert resp.status_code == 200
        assert resp.json()["opacity"] == 0.75

    def test_update_collapsed(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH toggles the collapsed flag."""
        _, client = api_env
        cluster = _create_cluster(client, name="collapse-test")
        assert cluster["collapsed"] is False

        resp = client.patch(
            f"/api/clusters/{cluster['id']}",
            json={"collapsed": True},
        )
        assert resp.status_code == 200
        assert resp.json()["collapsed"] is True

    def test_update_sets_updated_at(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH refreshes the updated_at timestamp."""
        _, client = api_env
        cluster = _create_cluster(client, name="ts-check")
        original_updated = cluster["updated_at"]

        resp = client.patch(
            f"/api/clusters/{cluster['id']}",
            json={"color": "#FF0000"},
        )
        assert resp.status_code == 200
        new_updated = resp.json()["updated_at"]
        assert new_updated >= original_updated

    def test_update_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH on a non-existent ID returns 404."""
        _, client = api_env
        resp = client.patch(
            "/api/clusters/00000000000000000000000000",
            json={"name": "ghost"},
        )
        assert resp.status_code == 404

    def test_update_invalid_opacity(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with opacity outside 0.0-1.0 returns 422."""
        _, client = api_env
        cluster = _create_cluster(client, name="bad-patch")

        resp = client.patch(
            f"/api/clusters/{cluster['id']}",
            json={"opacity": 2.0},
        )
        assert resp.status_code == 422

    def test_partial_update_preserves_other_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH on one field leaves unrelated fields unchanged."""
        _, client = api_env
        cluster = _create_cluster(
            client,
            name="preserve-me",
            color="#AABBCC",
            opacity=0.5,
            collapsed=True,
        )

        resp = client.patch(
            f"/api/clusters/{cluster['id']}",
            json={"name": "changed-name"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "changed-name"
        assert data["color"] == "#AABBCC"
        assert data["opacity"] == 0.5
        assert data["collapsed"] is True


class TestClusterDelete:
    """DELETE /api/clusters/{id} -- hard-delete endpoint."""

    def test_delete_cluster(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Hard-delete returns 200 with {"ok": true}."""
        _, client = api_env
        cluster = _create_cluster(client, name="to-delete")

        resp = client.delete(f"/api/clusters/{cluster['id']}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Cluster no longer appears in list
        list_resp = client.get("/api/clusters")
        ids = [c["id"] for c in list_resp.json()]
        assert cluster["id"] not in ids

    def test_delete_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """DELETE on a non-existent ID returns 404."""
        _, client = api_env
        resp = client.delete("/api/clusters/00000000000000000000000000")
        assert resp.status_code == 404

    def test_delete_cascades_project_clusters(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Deleting a cluster cascades and removes ProjectCluster rows."""
        session, client = api_env
        cluster = _create_cluster(client, name="cascade-test")
        project = _create_project(client, name="member-proj", path="/tmp/member")

        # Add project to cluster
        add_resp = client.post(
            f"/api/clusters/{cluster['id']}/projects",
            json={"project_id": project["id"]},
        )
        assert add_resp.status_code == 201

        # Verify the link exists
        links_before = session.exec(
            select(ProjectCluster).where(
                ProjectCluster.cluster_id == cluster["id"]
            )
        ).all()
        assert len(links_before) == 1

        # Delete the cluster
        del_resp = client.delete(f"/api/clusters/{cluster['id']}")
        assert del_resp.status_code == 200

        # Verify the ProjectCluster row was cascaded away
        session.expire_all()
        links_after = session.exec(
            select(ProjectCluster).where(
                ProjectCluster.cluster_id == cluster["id"]
            )
        ).all()
        assert len(links_after) == 0


class TestClusterMembership:
    """POST/DELETE /api/clusters/{id}/projects -- membership endpoints."""

    def test_add_project_to_cluster(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Adding a valid project to a valid cluster returns 201."""
        _, client = api_env
        cluster = _create_cluster(client, name="my-cluster")
        project = _create_project(client, name="my-proj", path="/tmp/add")

        resp = client.post(
            f"/api/clusters/{cluster['id']}/projects",
            json={"project_id": project["id"]},
        )
        assert resp.status_code == 201
        assert resp.json() == {"ok": True}

    def test_add_project_cluster_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Adding to a non-existent cluster returns 404."""
        _, client = api_env
        project = _create_project(client, name="orphan-proj", path="/tmp/orphan")

        resp = client.post(
            "/api/clusters/00000000000000000000000000/projects",
            json={"project_id": project["id"]},
        )
        assert resp.status_code == 404
        assert "cluster" in resp.json()["detail"].lower()

    def test_add_project_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Adding a non-existent project returns 404."""
        _, client = api_env
        cluster = _create_cluster(client, name="lonely-cluster")

        resp = client.post(
            f"/api/clusters/{cluster['id']}/projects",
            json={"project_id": "00000000000000000000000000"},
        )
        assert resp.status_code == 404
        assert "project" in resp.json()["detail"].lower()

    def test_add_project_duplicate(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Adding the same project twice to a cluster returns 409."""
        _, client = api_env
        cluster = _create_cluster(client, name="dup-cluster")
        project = _create_project(client, name="dup-proj", path="/tmp/dup")

        # First add succeeds
        resp1 = client.post(
            f"/api/clusters/{cluster['id']}/projects",
            json={"project_id": project["id"]},
        )
        assert resp1.status_code == 201

        # Second add conflicts
        resp2 = client.post(
            f"/api/clusters/{cluster['id']}/projects",
            json={"project_id": project["id"]},
        )
        assert resp2.status_code == 409

    def test_remove_project_from_cluster(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Removing a membership returns 200 with {"ok": true}."""
        _, client = api_env
        cluster = _create_cluster(client, name="remove-cluster")
        project = _create_project(client, name="remove-proj", path="/tmp/remove")

        # Add then remove
        client.post(
            f"/api/clusters/{cluster['id']}/projects",
            json={"project_id": project["id"]},
        )
        resp = client.delete(
            f"/api/clusters/{cluster['id']}/projects/{project['id']}"
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_remove_project_not_in_cluster(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Removing a project that is not in the cluster returns 404."""
        _, client = api_env
        cluster = _create_cluster(client, name="empty-cluster")
        project = _create_project(client, name="never-added", path="/tmp/never")

        resp = client.delete(
            f"/api/clusters/{cluster['id']}/projects/{project['id']}"
        )
        assert resp.status_code == 404

    def test_project_in_multiple_clusters(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A single project can belong to multiple clusters simultaneously."""
        _, client = api_env
        cluster_a = _create_cluster(client, name="cluster-a")
        cluster_b = _create_cluster(client, name="cluster-b")
        project = _create_project(client, name="shared-proj", path="/tmp/shared")

        resp_a = client.post(
            f"/api/clusters/{cluster_a['id']}/projects",
            json={"project_id": project["id"]},
        )
        assert resp_a.status_code == 201

        resp_b = client.post(
            f"/api/clusters/{cluster_b['id']}/projects",
            json={"project_id": project["id"]},
        )
        assert resp_b.status_code == 201

        # Removing from one cluster does not affect the other
        del_resp = client.delete(
            f"/api/clusters/{cluster_a['id']}/projects/{project['id']}"
        )
        assert del_resp.status_code == 200

        # Project is still in cluster_b — re-removing from cluster_a fails
        retry_resp = client.delete(
            f"/api/clusters/{cluster_a['id']}/projects/{project['id']}"
        )
        assert retry_resp.status_code == 404


class TestClusterResponseShape:
    """Verify the JSON shape returned by the clusters endpoints."""

    def test_response_contains_all_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """The response includes every field from ClusterPublic."""
        _, client = api_env
        data = _create_cluster(
            client,
            name="shape-check",
            color="#FF5500",
            opacity=0.6,
            collapsed=True,
        )

        expected_keys = {
            "id",
            "name",
            "color",
            "opacity",
            "collapsed",
            "created_at",
            "updated_at",
        }
        actual_keys = set(data.keys())
        missing = expected_keys - actual_keys
        assert not missing, f"Missing expected keys: {missing}"
        extra = actual_keys - expected_keys
        assert not extra, f"Unexpected extra keys: {extra}"

    def test_response_excludes_relationships(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Response JSON contains data columns but not ORM relationships."""
        _, client = api_env
        data = _create_cluster(client, name="no-rels")

        # Relationship keys must NOT be present
        forbidden_keys = {"project_links"}
        for key in forbidden_keys:
            assert key not in data, f"Unexpected relationship key '{key}' in response"
