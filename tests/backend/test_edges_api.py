"""Tests for the FastAPI edges CRUD router.

Covers all four endpoints on ``/api/edges``: list (with filters),
create, partial update, and hard delete.  Each test class targets a
single responsibility area so failures are easy to localise.

Every test uses an isolated, in-memory-like SQLite database created in
``tmp_path`` with real migrations applied, ensuring schema parity with
production.
"""

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session
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
from models import Edge, Project  # noqa: E402

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
        direct ORM setup and *client* is a ``TestClient`` wired to the
        FastAPI app with the overridden session dependency.
    """
    db_path = tmp_path / "test_edges_api.db"
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

_project_counter = 0


def _create_project(client: TestClient, **overrides: Any) -> dict[str, Any]:
    """POST a new project and return the JSON response body.

    Generates a unique ``name`` and ``path`` for each call to avoid
    duplicate-path conflicts across tests.
    """
    global _project_counter
    _project_counter += 1
    payload: dict[str, Any] = {
        "name": f"edge-test-proj-{_project_counter}",
        "path": f"/tmp/edge-test-proj-{_project_counter}",
    }
    payload.update(overrides)
    resp = client.post("/api/projects", json=payload)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    return resp.json()


def _create_edge(
    client: TestClient, source_id: str, target_id: str, **overrides: Any
) -> dict[str, Any]:
    """POST a new edge between two projects and return the JSON response body.

    Provides ``source_id`` and ``target_id`` as positional arguments.
    Additional fields can be overridden via keyword arguments.
    """
    payload: dict[str, Any] = {
        "source_id": source_id,
        "target_id": target_id,
    }
    payload.update(overrides)
    resp = client.post("/api/edges", json=payload)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    return resp.json()


# ===========================================================================
# Test classes
# ===========================================================================


class TestEdgeCreate:
    """POST /api/edges -- creation endpoint."""

    def test_create_edge_minimal(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Minimal payload (source_id + target_id) returns 201 with defaults."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)

        data = _create_edge(client, p1["id"], p2["id"])

        # ULID: 26-char Crockford Base32
        assert len(data["id"]) == 26
        assert set(data["id"]).issubset(_ULID_CHARSET)

        # Source and target recorded correctly
        assert data["source_id"] == p1["id"]
        assert data["target_id"] == p2["id"]

        # Defaults
        assert data["weight"] == 0.5
        assert data["label"] is None
        assert data["color_override"] is None
        assert data["directed"] is False

        # Timestamps populated
        assert data["created_at"] is not None
        assert data["updated_at"] is not None

    def test_create_edge_all_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """All user-settable fields round-trip correctly."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)

        data = _create_edge(
            client,
            p1["id"],
            p2["id"],
            weight=0.85,
            label="depends-on",
            color_override="#FF5500",
            directed=True,
        )

        assert data["weight"] == 0.85
        assert data["label"] == "depends-on"
        assert data["color_override"] == "#FF5500"
        assert data["directed"] is True

    def test_create_edge_type_forced_manual(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """The edge_type is always forced to 'manual' regardless of input."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)

        data = _create_edge(client, p1["id"], p2["id"])
        assert data["edge_type"] == "manual"

    def test_create_edge_self_loop(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Creating an edge with the same source and target returns 409."""
        _, client = api_env
        p1 = _create_project(client)

        resp = client.post(
            "/api/edges",
            json={"source_id": p1["id"], "target_id": p1["id"]},
        )
        assert resp.status_code == 409
        assert "self-referential" in resp.json()["detail"].lower()

    def test_create_edge_source_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A non-existent source_id returns 404."""
        _, client = api_env
        p1 = _create_project(client)

        resp = client.post(
            "/api/edges",
            json={
                "source_id": "00000000000000000000000000",
                "target_id": p1["id"],
            },
        )
        assert resp.status_code == 404
        assert "source" in resp.json()["detail"].lower()

    def test_create_edge_target_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A non-existent target_id returns 404."""
        _, client = api_env
        p1 = _create_project(client)

        resp = client.post(
            "/api/edges",
            json={
                "source_id": p1["id"],
                "target_id": "00000000000000000000000000",
            },
        )
        assert resp.status_code == 404
        assert "target" in resp.json()["detail"].lower()

    def test_create_edge_duplicate(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Duplicate edge (same source, target, type) returns 409."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)

        _create_edge(client, p1["id"], p2["id"])

        resp = client.post(
            "/api/edges",
            json={"source_id": p1["id"], "target_id": p2["id"]},
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"].lower()

    def test_create_edge_weight_below_zero(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A negative weight returns 422."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)

        resp = client.post(
            "/api/edges",
            json={
                "source_id": p1["id"],
                "target_id": p2["id"],
                "weight": -0.1,
            },
        )
        assert resp.status_code == 422

    def test_create_edge_weight_above_one(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A weight greater than 1.0 returns 422."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)

        resp = client.post(
            "/api/edges",
            json={
                "source_id": p1["id"],
                "target_id": p2["id"],
                "weight": 1.5,
            },
        )
        assert resp.status_code == 422


class TestEdgeRead:
    """GET /api/edges -- list endpoint with optional filters."""

    def test_list_edges_empty(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Empty database returns an empty list."""
        _, client = api_env
        resp = client.get("/api/edges")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_edges_returns_all(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """All created edges appear in the list."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        p3 = _create_project(client)

        e1 = _create_edge(client, p1["id"], p2["id"])
        e2 = _create_edge(client, p2["id"], p3["id"])

        resp = client.get("/api/edges")
        assert resp.status_code == 200
        ids = {e["id"] for e in resp.json()}
        assert ids == {e1["id"], e2["id"]}

    def test_filter_by_source_id(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Only edges matching the source_id filter are returned."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        p3 = _create_project(client)

        e1 = _create_edge(client, p1["id"], p2["id"])
        _create_edge(client, p2["id"], p3["id"])

        resp = client.get("/api/edges", params={"source_id": p1["id"]})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["id"] == e1["id"]

    def test_filter_by_target_id(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Only edges matching the target_id filter are returned."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        p3 = _create_project(client)

        _create_edge(client, p1["id"], p2["id"])
        e2 = _create_edge(client, p2["id"], p3["id"])

        resp = client.get("/api/edges", params={"target_id": p3["id"]})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["id"] == e2["id"]

    def test_filter_by_edge_type(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Only edges matching the edge_type filter are returned."""
        session, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        p3 = _create_project(client)

        # Create a manual edge via the API
        manual_edge = _create_edge(client, p1["id"], p2["id"])

        # Insert an auto_tech edge directly via ORM to simulate scanner output
        auto_edge = Edge(
            source_id=p2["id"],
            target_id=p3["id"],
            edge_type="auto_tech",
            weight=0.7,
            directed=False,
            created_at=_NOW,
            updated_at=_NOW,
        )
        session.add(auto_edge)
        session.commit()
        session.refresh(auto_edge)

        # Filter for manual only
        resp = client.get("/api/edges", params={"edge_type": "manual"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["id"] == manual_edge["id"]

        # Filter for auto_tech only
        resp = client.get("/api/edges", params={"edge_type": "auto_tech"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["id"] == auto_edge.id


class TestEdgeUpdate:
    """PATCH /api/edges/{edge_id} -- partial update endpoint."""

    def test_update_weight(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with a new weight updates only the weight."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        edge = _create_edge(client, p1["id"], p2["id"], weight=0.3)

        resp = client.patch(
            f"/api/edges/{edge['id']}",
            json={"weight": 0.9},
        )
        assert resp.status_code == 200
        assert resp.json()["weight"] == 0.9

    def test_update_label(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with a new label updates only the label."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        edge = _create_edge(client, p1["id"], p2["id"])

        resp = client.patch(
            f"/api/edges/{edge['id']}",
            json={"label": "shared-utils"},
        )
        assert resp.status_code == 200
        assert resp.json()["label"] == "shared-utils"

    def test_update_directed(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with directed=True updates the directed flag."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        edge = _create_edge(client, p1["id"], p2["id"], directed=False)

        resp = client.patch(
            f"/api/edges/{edge['id']}",
            json={"directed": True},
        )
        assert resp.status_code == 200
        assert resp.json()["directed"] is True

    def test_update_sets_updated_at(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH refreshes the updated_at timestamp."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        edge = _create_edge(client, p1["id"], p2["id"])
        original_updated = edge["updated_at"]

        resp = client.patch(
            f"/api/edges/{edge['id']}",
            json={"label": "touched"},
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
            "/api/edges/00000000000000000000000000",
            json={"weight": 0.5},
        )
        assert resp.status_code == 404

    def test_update_invalid_weight(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with an invalid weight returns 422."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        edge = _create_edge(client, p1["id"], p2["id"])

        resp = client.patch(
            f"/api/edges/{edge['id']}",
            json={"weight": 2.0},
        )
        assert resp.status_code == 422

    def test_partial_update_preserves_other_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH on one field leaves unrelated fields unchanged."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        edge = _create_edge(
            client,
            p1["id"],
            p2["id"],
            weight=0.7,
            label="original-label",
            color_override="#00FF00",
            directed=True,
        )

        resp = client.patch(
            f"/api/edges/{edge['id']}",
            json={"label": "new-label"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "new-label"
        assert data["weight"] == 0.7
        assert data["color_override"] == "#00FF00"
        assert data["directed"] is True
        assert data["source_id"] == p1["id"]
        assert data["target_id"] == p2["id"]

    def test_update_auto_edge_rejected(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH on an auto-computed edge returns 403."""
        session, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)

        # Insert an auto_tech edge directly via ORM
        edge = Edge(
            source_id=p1["id"],
            target_id=p2["id"],
            edge_type="auto_tech",
            weight=0.5,
            created_at=_NOW,
            updated_at=_NOW,
        )
        session.add(edge)
        session.commit()
        session.refresh(edge)

        resp = client.patch(f"/api/edges/{edge.id}", json={"weight": 0.9})
        assert resp.status_code == 403


class TestEdgeDelete:
    """DELETE /api/edges/{edge_id} -- hard delete endpoint."""

    def test_delete_edge(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Hard-delete returns 200 with {"ok": true}."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        edge = _create_edge(client, p1["id"], p2["id"])

        resp = client.delete(f"/api/edges/{edge['id']}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Confirm edge is actually gone
        list_resp = client.get("/api/edges")
        ids = [e["id"] for e in list_resp.json()]
        assert edge["id"] not in ids

    def test_delete_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """DELETE on a non-existent ID returns 404."""
        _, client = api_env
        resp = client.delete("/api/edges/00000000000000000000000000")
        assert resp.status_code == 404

    def test_delete_auto_edge_rejected(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """DELETE on an auto-computed edge returns 403."""
        session, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)

        edge = Edge(
            source_id=p1["id"],
            target_id=p2["id"],
            edge_type="auto_tech",
            weight=0.5,
            created_at=_NOW,
            updated_at=_NOW,
        )
        session.add(edge)
        session.commit()
        session.refresh(edge)

        resp = client.delete(f"/api/edges/{edge.id}")
        assert resp.status_code == 403


class TestEdgeResponseShape:
    """Verify the JSON shape returned by the edges endpoints."""

    def test_response_contains_all_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Response JSON contains all expected EdgePublic keys."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        edge = _create_edge(
            client,
            p1["id"],
            p2["id"],
            weight=0.6,
            label="test-label",
            color_override="#AABBCC",
            directed=True,
        )

        expected_keys = {
            "id",
            "source_id",
            "target_id",
            "edge_type",
            "weight",
            "label",
            "color_override",
            "directed",
            "edge_metadata",
            "created_at",
            "updated_at",
        }
        actual_keys = set(edge.keys())
        missing = expected_keys - actual_keys
        assert not missing, f"Missing expected keys: {missing}"

    def test_response_excludes_relationships(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Response JSON does not include ORM relationship keys."""
        _, client = api_env
        p1 = _create_project(client)
        p2 = _create_project(client)
        edge = _create_edge(client, p1["id"], p2["id"])

        # Relationship keys must NOT be present
        forbidden_keys = {"source", "target"}
        for key in forbidden_keys:
            assert key not in edge, (
                f"Unexpected relationship key '{key}' in response"
            )
