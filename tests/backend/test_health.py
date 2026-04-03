"""Smoke tests for the /api/health endpoint and sidecar package structure."""

from __future__ import annotations

import config
from starlette.testclient import TestClient


def test_health_returns_200(client: TestClient) -> None:
    """GET /api/health should return HTTP 200."""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_health_response_body(client: TestClient) -> None:
    """Response body must contain the expected status and version."""
    response = client.get("/api/health")
    assert response.json() == {"status": "ok", "version": config.SIDECAR_VERSION}


def test_health_content_type(client: TestClient) -> None:
    """Response content-type must be application/json."""
    response = client.get("/api/health")
    assert response.headers["content-type"] == "application/json"


def test_subpackage_imports() -> None:
    """All sidecar subpackages should be importable without errors."""
    import models  # noqa: F401
    import scanner  # noqa: F401
    import scanner.analyzers  # noqa: F401
    import api  # noqa: F401
    import db  # noqa: F401
    import utils  # noqa: F401
