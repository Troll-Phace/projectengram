"""Tests for the FastAPI config key-value store router.

Covers both endpoints on ``/api/config``: listing all entries and
upserting individual entries by key.  Each test class targets a single
responsibility area so failures are easy to localise.

Every test uses an isolated SQLite database created in ``tmp_path`` with
real migrations applied, ensuring schema parity with production.  The
migration seeds four default config rows (``projects_root``,
``auto_edge_min_weight``, ``scan_interval_minutes``, ``sidecar_port``),
so the database is never empty on a fresh start.
"""

import json
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
from models import Config  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "sidecar" / "db" / "migrations"
)

# Keys seeded by the 0001_init.sql migration.
_SEEDED_KEYS = {
    "projects_root",
    "auto_edge_min_weight",
    "scan_interval_minutes",
    "sidecar_port",
}

# Expected fields in the ConfigPublic response model.
_EXPECTED_FIELDS = {"key", "value", "updated_at"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_env(tmp_path: Path) -> Iterator[tuple[Session, TestClient]]:
    """Create an isolated DB, run migrations, override the session dep.

    Yields:
        A ``(session, client)`` tuple where *session* can be used for
        direct ORM inspection and *client* is a ``TestClient`` wired to
        the FastAPI app with the overridden session dependency.
    """
    db_path = tmp_path / "test_config_api.db"
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


# ===========================================================================
# Test classes
# ===========================================================================


class TestConfigRead:
    """GET /api/config — listing all config entries."""

    def test_list_config_has_defaults(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Fresh DB should contain seeded entries from the migration."""
        _, client = api_env
        resp = client.get("/api/config")
        assert resp.status_code == 200

        entries = resp.json()
        keys = {entry["key"] for entry in entries}
        assert _SEEDED_KEYS.issubset(keys), (
            f"Missing seeded keys: {_SEEDED_KEYS - keys}"
        )

    def test_list_config_default_values_match_migration(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Seeded config values match those defined in the migration SQL."""
        _, client = api_env
        resp = client.get("/api/config")
        assert resp.status_code == 200

        by_key = {entry["key"]: entry["value"] for entry in resp.json()}
        assert by_key["projects_root"] == '"~/Documents"'
        assert by_key["auto_edge_min_weight"] == "0.3"
        assert by_key["scan_interval_minutes"] == "30"
        assert by_key["sidecar_port"] == "9721"

    def test_list_config_contains_custom(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A custom entry added via PATCH appears in the GET listing."""
        _, client = api_env

        # Create a custom config entry.
        client.patch("/api/config/custom_key", json={"value": "custom_value"})

        resp = client.get("/api/config")
        assert resp.status_code == 200

        keys = {entry["key"] for entry in resp.json()}
        assert "custom_key" in keys

        by_key = {entry["key"]: entry["value"] for entry in resp.json()}
        assert by_key["custom_key"] == "custom_value"

    def test_list_config_returns_list(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """GET /api/config always returns a JSON list."""
        _, client = api_env
        resp = client.get("/api/config")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestConfigUpsert:
    """PATCH /api/config/{key} — create or update a config entry."""

    def test_upsert_create_new_key(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH a key that does not exist creates it and returns 200."""
        _, client = api_env
        resp = client.patch(
            "/api/config/brand_new_key",
            json={"value": "hello"},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["key"] == "brand_new_key"
        assert data["value"] == "hello"

    def test_upsert_update_existing_key(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH a seeded key updates its value and returns 200."""
        _, client = api_env

        # Verify the original seeded value first.
        resp_before = client.get("/api/config")
        by_key_before = {e["key"]: e["value"] for e in resp_before.json()}
        assert by_key_before["sidecar_port"] == "9721"

        # Update the value.
        resp = client.patch(
            "/api/config/sidecar_port",
            json={"value": "8080"},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["key"] == "sidecar_port"
        assert data["value"] == "8080"

        # Confirm the update persists via GET.
        resp_after = client.get("/api/config")
        by_key_after = {e["key"]: e["value"] for e in resp_after.json()}
        assert by_key_after["sidecar_port"] == "8080"

    def test_upsert_sets_updated_at(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH sets the updated_at field on the returned entry."""
        _, client = api_env
        resp = client.patch(
            "/api/config/ts_check_key",
            json={"value": "v1"},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["updated_at"] is not None
        assert len(data["updated_at"]) > 0

    def test_upsert_updates_timestamp_on_change(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Successive PATCHes on the same key refresh updated_at."""
        _, client = api_env

        resp1 = client.patch(
            "/api/config/evolving_key",
            json={"value": "first"},
        )
        assert resp1.status_code == 200
        ts1 = resp1.json()["updated_at"]

        resp2 = client.patch(
            "/api/config/evolving_key",
            json={"value": "second"},
        )
        assert resp2.status_code == 200
        ts2 = resp2.json()["updated_at"]

        # Timestamps are ISO strings; lexicographic >= is correct.
        assert ts2 >= ts1

    def test_upsert_null_value(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with null value succeeds and stores null."""
        _, client = api_env
        resp = client.patch(
            "/api/config/nullable_key",
            json={"value": None},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["key"] == "nullable_key"
        assert data["value"] is None

    def test_upsert_null_value_on_existing_key(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH with null value clears an existing key's value."""
        _, client = api_env

        # First set a non-null value.
        client.patch("/api/config/clear_me", json={"value": "something"})

        # Now clear it.
        resp = client.patch("/api/config/clear_me", json={"value": None})
        assert resp.status_code == 200
        assert resp.json()["value"] is None

    def test_upsert_json_string(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A JSON-encoded string stored as the value round-trips correctly."""
        _, client = api_env
        json_payload = json.dumps({"nested": True, "count": 42})

        resp = client.patch(
            "/api/config/json_key",
            json={"value": json_payload},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["value"] == json_payload

        # Parse back to verify the JSON is intact.
        parsed = json.loads(data["value"])
        assert parsed == {"nested": True, "count": 42}

    def test_upsert_empty_string_value(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """An empty string is a valid value, distinct from null."""
        _, client = api_env
        resp = client.patch(
            "/api/config/empty_val",
            json={"value": ""},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["value"] == ""
        assert data["value"] is not None

    def test_upsert_long_value(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """A long string value is stored and returned without truncation."""
        _, client = api_env
        long_value = "x" * 10_000

        resp = client.patch(
            "/api/config/long_key",
            json={"value": long_value},
        )
        assert resp.status_code == 200
        assert resp.json()["value"] == long_value
        assert len(resp.json()["value"]) == 10_000

    def test_upsert_default_value_is_null(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Omitting the value field from the body defaults to null."""
        _, client = api_env
        resp = client.patch(
            "/api/config/default_null_key",
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()["value"] is None

    def test_upsert_persists_in_database(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """PATCH writes through to the database (verified via ORM query)."""
        session, client = api_env
        resp = client.patch(
            "/api/config/orm_check",
            json={"value": "persisted"},
        )
        assert resp.status_code == 200

        # Query via ORM to confirm persistence.
        row = session.get(Config, "orm_check")
        assert row is not None
        assert row.value == "persisted"


class TestConfigResponseShape:
    """Verify the JSON shape returned by the config endpoints."""

    def test_response_contains_all_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Each config entry has key, value, and updated_at."""
        _, client = api_env
        resp = client.patch(
            "/api/config/shape_key",
            json={"value": "shape_value"},
        )
        assert resp.status_code == 200
        data = resp.json()

        for field in _EXPECTED_FIELDS:
            assert field in data, f"Missing expected field '{field}' in response"

    def test_response_no_extra_fields(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Response contains only the expected keys, nothing extra."""
        _, client = api_env
        resp = client.patch(
            "/api/config/strict_key",
            json={"value": "strict_value"},
        )
        assert resp.status_code == 200
        data = resp.json()

        actual_keys = set(data.keys())
        extra = actual_keys - _EXPECTED_FIELDS
        assert not extra, f"Unexpected keys in response: {extra}"

    def test_list_response_items_have_correct_shape(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """Every item in the GET list response has exactly the expected fields."""
        _, client = api_env
        resp = client.get("/api/config")
        assert resp.status_code == 200

        entries = resp.json()
        assert len(entries) > 0, "Expected at least the seeded config entries"

        for entry in entries:
            actual_keys = set(entry.keys())
            assert actual_keys == _EXPECTED_FIELDS, (
                f"Entry '{entry.get('key')}' has unexpected shape: {actual_keys}"
            )

    def test_updated_at_is_iso_format(
        self, api_env: tuple[Session, TestClient]
    ) -> None:
        """The updated_at field follows ISO 8601 format."""
        _, client = api_env
        resp = client.patch(
            "/api/config/iso_key",
            json={"value": "iso_value"},
        )
        assert resp.status_code == 200

        updated_at = resp.json()["updated_at"]
        # The router formats as YYYY-MM-DDTHH:MM:SSZ (20 chars).
        assert "T" in updated_at
        assert updated_at.endswith("Z")
