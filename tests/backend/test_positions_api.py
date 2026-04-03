"""Tests for the FastAPI node-positions router.

Covers all three endpoints on ``/api/positions``: list all positions,
partial update of a single position, and batch upsert.  Each test
class targets a single responsibility area so failures are easy to
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
# sys.path setup -- mirrors conftest.py convention
# ---------------------------------------------------------------------------

_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from db.engine import get_engine  # noqa: E402
from db.migrations.migrator import DatabaseMigrator  # noqa: E402
from db.session import get_session  # noqa: E402
from main import app  # noqa: E402
from models import NodePosition, Project  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "sidecar" / "db" / "migrations"
)
_NOW = "2025-06-01T00:00:00Z"


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
    db_path = tmp_path / "test_positions_api.db"
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


def _create_position_via_orm(
    session: Session,
    project_id: str,
    *,
    x: float = 0.0,
    y: float = 0.0,
    pinned: bool = False,
    updated_at: str = _NOW,
) -> NodePosition:
    """Insert a ``NodePosition`` row directly via the ORM.

    Returns the persisted model instance.
    """
    pos = NodePosition(
        project_id=project_id,
        x=x,
        y=y,
        pinned=pinned,
        updated_at=updated_at,
    )
    session.add(pos)
    session.commit()
    session.refresh(pos)
    return pos


# ===========================================================================
# Test classes
# ===========================================================================


class TestPositionRead:
    """GET /api/positions -- list endpoint."""

    def test_list_positions_empty(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Empty database returns an empty list."""
        _, client = api_env
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_positions_returns_all(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """All created positions appear in the list."""
        session, client = api_env

        # Create three projects and corresponding positions
        projects = []
        for i, name in enumerate(("alpha", "beta", "gamma")):
            proj = _create_project(client, name=name, path=f"/tmp/{name}")
            projects.append(proj)
            _create_position_via_orm(
                session,
                proj["id"],
                x=float(i * 100),
                y=float(i * 50),
            )

        resp = client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3

        returned_ids = {p["project_id"] for p in data}
        expected_ids = {p["id"] for p in projects}
        assert returned_ids == expected_ids


class TestPositionUpdate:
    """PATCH /api/positions/{project_id} -- partial update endpoint."""

    def test_update_x_y(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with new x and y updates both coordinates."""
        session, client = api_env
        proj = _create_project(client, name="xy-update", path="/tmp/xy")
        _create_position_via_orm(session, proj["id"], x=10.0, y=20.0)

        resp = client.patch(
            f"/api/positions/{proj['id']}",
            json={"x": 300.5, "y": 450.75},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["x"] == 300.5
        assert data["y"] == 450.75

    def test_update_pinned(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with pinned=True toggles the pinned state."""
        session, client = api_env
        proj = _create_project(client, name="pin-toggle", path="/tmp/pin")
        _create_position_via_orm(session, proj["id"], pinned=False)

        resp = client.patch(
            f"/api/positions/{proj['id']}",
            json={"pinned": True},
        )
        assert resp.status_code == 200
        assert resp.json()["pinned"] is True

        # Toggle back to False
        resp2 = client.patch(
            f"/api/positions/{proj['id']}",
            json={"pinned": False},
        )
        assert resp2.status_code == 200
        assert resp2.json()["pinned"] is False

    def test_update_sets_updated_at(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH refreshes the updated_at timestamp."""
        session, client = api_env
        proj = _create_project(client, name="ts-check", path="/tmp/ts-check")
        _create_position_via_orm(
            session, proj["id"], x=0.0, y=0.0, updated_at=_NOW
        )

        resp = client.patch(
            f"/api/positions/{proj['id']}",
            json={"x": 999.0},
        )
        assert resp.status_code == 200
        new_updated = resp.json()["updated_at"]
        # The updated_at should have been refreshed to a time >= the
        # original static value we seeded.
        assert new_updated >= _NOW

    def test_update_not_found(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH on a non-existent position returns 404."""
        _, client = api_env
        resp = client.patch(
            "/api/positions/00000000000000000000000000",
            json={"x": 1.0},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_partial_update_preserves_other_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH on one field leaves unrelated fields unchanged."""
        session, client = api_env
        proj = _create_project(client, name="preserve", path="/tmp/preserve")
        _create_position_via_orm(
            session, proj["id"], x=100.0, y=200.0, pinned=True
        )

        # Update only x -- y and pinned should remain unchanged
        resp = client.patch(
            f"/api/positions/{proj['id']}",
            json={"x": 999.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["x"] == 999.0
        assert data["y"] == 200.0
        assert data["pinned"] is True


class TestPositionBatch:
    """POST /api/positions/batch -- batch upsert endpoint."""

    def test_batch_create_new_positions(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Batch creates positions for projects that have none yet."""
        _, client = api_env
        proj_a = _create_project(client, name="batch-a", path="/tmp/ba")
        proj_b = _create_project(client, name="batch-b", path="/tmp/bb")

        resp = client.post(
            "/api/positions/batch",
            json={
                "positions": [
                    {"project_id": proj_a["id"], "x": 10.0, "y": 20.0},
                    {
                        "project_id": proj_b["id"],
                        "x": 30.0,
                        "y": 40.0,
                        "pinned": True,
                    },
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        by_id = {p["project_id"]: p for p in data}

        assert by_id[proj_a["id"]]["x"] == 10.0
        assert by_id[proj_a["id"]]["y"] == 20.0
        assert by_id[proj_a["id"]]["pinned"] is False  # default

        assert by_id[proj_b["id"]]["x"] == 30.0
        assert by_id[proj_b["id"]]["y"] == 40.0
        assert by_id[proj_b["id"]]["pinned"] is True

    def test_batch_update_existing(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Batch updates positions that already exist."""
        session, client = api_env
        proj = _create_project(client, name="batch-upd", path="/tmp/bupd")
        _create_position_via_orm(session, proj["id"], x=1.0, y=2.0, pinned=False)

        resp = client.post(
            "/api/positions/batch",
            json={
                "positions": [
                    {
                        "project_id": proj["id"],
                        "x": 500.0,
                        "y": 600.0,
                        "pinned": True,
                    }
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["x"] == 500.0
        assert data[0]["y"] == 600.0
        assert data[0]["pinned"] is True

        # Verify via GET that the update persisted
        list_resp = client.get("/api/positions")
        assert list_resp.status_code == 200
        positions = list_resp.json()
        assert len(positions) == 1
        assert positions[0]["x"] == 500.0

    def test_batch_mixed_create_update(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Batch handles a mix of new and existing positions."""
        session, client = api_env
        proj_existing = _create_project(
            client, name="batch-mix-exist", path="/tmp/bme"
        )
        proj_new = _create_project(
            client, name="batch-mix-new", path="/tmp/bmn"
        )

        # Pre-create a position only for the existing project
        _create_position_via_orm(
            session, proj_existing["id"], x=1.0, y=1.0
        )

        resp = client.post(
            "/api/positions/batch",
            json={
                "positions": [
                    {
                        "project_id": proj_existing["id"],
                        "x": 100.0,
                        "y": 100.0,
                        "pinned": True,
                    },
                    {
                        "project_id": proj_new["id"],
                        "x": 200.0,
                        "y": 200.0,
                    },
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        by_id = {p["project_id"]: p for p in data}

        # Existing position was updated
        assert by_id[proj_existing["id"]]["x"] == 100.0
        assert by_id[proj_existing["id"]]["pinned"] is True

        # New position was created
        assert by_id[proj_new["id"]]["x"] == 200.0
        assert by_id[proj_new["id"]]["y"] == 200.0
        assert by_id[proj_new["id"]]["pinned"] is False

    def test_batch_invalid_project_id(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Batch with a non-existent project_id returns 400."""
        _, client = api_env
        resp = client.post(
            "/api/positions/batch",
            json={
                "positions": [
                    {
                        "project_id": "00000000000000000000000000",
                        "x": 1.0,
                        "y": 2.0,
                    }
                ]
            },
        )
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"].lower()

    def test_batch_invalid_project_id_rolls_back(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """When one project_id is invalid, no positions are written."""
        _, client = api_env
        proj_good = _create_project(
            client, name="good-proj", path="/tmp/good"
        )

        resp = client.post(
            "/api/positions/batch",
            json={
                "positions": [
                    {"project_id": proj_good["id"], "x": 1.0, "y": 2.0},
                    {
                        "project_id": "00000000000000000000000000",
                        "x": 3.0,
                        "y": 4.0,
                    },
                ]
            },
        )
        assert resp.status_code == 400

        # The valid project's position should NOT have been written
        list_resp = client.get("/api/positions")
        assert list_resp.status_code == 200
        assert list_resp.json() == []

    def test_batch_empty_list(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Batch with an empty positions list returns 200 and []."""
        _, client = api_env
        resp = client.post(
            "/api/positions/batch",
            json={"positions": []},
        )
        assert resp.status_code == 200
        assert resp.json() == []


class TestPositionResponseShape:
    """Verify the JSON shape returned by the positions endpoints."""

    def test_response_contains_all_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Every expected field is present in the response."""
        session, client = api_env
        proj = _create_project(client, name="shape-check", path="/tmp/shape")
        _create_position_via_orm(
            session, proj["id"], x=42.0, y=84.0, pinned=True
        )

        resp = client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

        position = data[0]

        expected_keys = {"project_id", "x", "y", "pinned", "updated_at"}
        actual_keys = set(position.keys())
        missing = expected_keys - actual_keys
        assert not missing, f"Missing expected keys: {missing}"

        # Verify types
        assert isinstance(position["project_id"], str)
        assert isinstance(position["x"], float)
        assert isinstance(position["y"], float)
        assert isinstance(position["pinned"], bool)
        assert isinstance(position["updated_at"], str)

    def test_response_excludes_relationships(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Response JSON must not contain ORM relationship keys."""
        session, client = api_env
        proj = _create_project(
            client, name="no-rels", path="/tmp/no-rels"
        )
        _create_position_via_orm(session, proj["id"], x=1.0, y=2.0)

        resp = client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

        forbidden_keys = {"project"}
        for key in forbidden_keys:
            assert key not in data[0], (
                f"Unexpected relationship key '{key}' in response"
            )

    def test_patch_response_shape(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH endpoint returns the same shape as the list endpoint."""
        session, client = api_env
        proj = _create_project(
            client, name="patch-shape", path="/tmp/patch-shape"
        )
        _create_position_via_orm(session, proj["id"], x=1.0, y=2.0)

        resp = client.patch(
            f"/api/positions/{proj['id']}",
            json={"x": 50.0},
        )
        assert resp.status_code == 200
        data = resp.json()

        expected_keys = {"project_id", "x", "y", "pinned", "updated_at"}
        actual_keys = set(data.keys())
        missing = expected_keys - actual_keys
        assert not missing, f"Missing expected keys: {missing}"
        assert "project" not in data

    def test_batch_response_shape(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Batch endpoint returns the same shape per item as list."""
        _, client = api_env
        proj = _create_project(
            client, name="batch-shape", path="/tmp/batch-shape"
        )

        resp = client.post(
            "/api/positions/batch",
            json={
                "positions": [
                    {"project_id": proj["id"], "x": 10.0, "y": 20.0}
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

        expected_keys = {"project_id", "x", "y", "pinned", "updated_at"}
        actual_keys = set(data[0].keys())
        missing = expected_keys - actual_keys
        assert not missing, f"Missing expected keys: {missing}"
        assert "project" not in data[0]
