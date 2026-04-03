"""Shared pytest fixtures for backend tests."""

import sys
from pathlib import Path
from typing import Iterator

import pytest
from starlette.testclient import TestClient

# The sidecar package uses bare imports (e.g. `import config`) that resolve
# only when the sidecar directory is on sys.path.  This mirrors how the
# sidecar runs in production (uvicorn launched from the sidecar/ directory).
_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from main import app  # noqa: E402


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """Yield a Starlette TestClient wired to the FastAPI application."""
    with TestClient(app) as c:
        yield c
