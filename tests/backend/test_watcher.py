"""Tests for the project file watcher module.

Covers watcher lifecycle (dormant states), change routing (known
project files, new/deleted directories, unknown projects, paths
outside root), the debounce-to-orchestrator callback, and graceful
stop when dormant.

All filesystem monitoring (``watchfiles.awatch``), database queries,
and orchestrator calls are mocked — these tests exercise routing
logic only.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from watchfiles import Change

# ---------------------------------------------------------------------------
# sys.path setup — mirrors conftest.py convention
# ---------------------------------------------------------------------------

_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from scanner.watcher import ProjectWatcher

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WATCHER_MODULE = "scanner.watcher"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator() -> MagicMock:
    """Create a mock ``ScanOrchestrator`` with async entry points."""
    orch = MagicMock()
    orch.trigger_full_scan = AsyncMock()
    orch.trigger_incremental_scan = AsyncMock()
    return orch


def _make_known_project(path: str, project_id: str) -> MagicMock:
    """Create a mock ``KnownProject`` with ``path`` and ``id`` attrs."""
    kp = MagicMock()
    kp.path = path
    kp.id = project_id
    return kp


# ===========================================================================
# Tests — Lifecycle / Dormant States
# ===========================================================================


class TestWatcherLifecycle:
    """Watcher ``start()`` dormant-state handling."""

    @pytest.mark.asyncio
    @patch(f"{_WATCHER_MODULE}._read_projects_root", return_value=None)
    async def test_start_dormant_when_no_config(
        self, mock_read_root: MagicMock
    ) -> None:
        """When ``projects_root`` is not configured in the database the
        watcher should remain dormant — no background task started."""
        orch = _make_orchestrator()
        watcher = ProjectWatcher(orch)

        await watcher.start()

        assert watcher._task is None

    @pytest.mark.asyncio
    @patch(f"{_WATCHER_MODULE}._query_known_projects", return_value=[])
    @patch(f"{_WATCHER_MODULE}._read_projects_root")
    async def test_start_dormant_when_path_not_directory(
        self,
        mock_read_root: MagicMock,
        mock_query: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When ``projects_root`` resolves to a path that is not an
        existing directory the watcher should remain dormant."""
        non_existent = str(tmp_path / "does-not-exist")
        mock_read_root.return_value = non_existent

        orch = _make_orchestrator()
        watcher = ProjectWatcher(orch)

        await watcher.start()

        assert watcher._task is None


# ===========================================================================
# Tests — Change Handling
# ===========================================================================


class TestHandleChange:
    """Routing logic inside ``_handle_change``."""

    @pytest.mark.asyncio
    async def test_handle_change_file_in_known_project(
        self, tmp_path: Path
    ) -> None:
        """A file modification inside a known project directory should
        trigger the debouncer with the correct project ID."""
        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        project_dir = projects_root / "myproject"
        project_dir.mkdir()

        orch = _make_orchestrator()
        watcher = ProjectWatcher(orch)
        watcher._projects_root = projects_root.resolve()
        watcher._path_to_project_id = {
            str(project_dir.resolve()): "proj-abc",
        }
        watcher._debouncer = MagicMock()
        watcher._debouncer.trigger = AsyncMock()

        changed_file = str(project_dir / "src" / "main.py")
        await watcher._handle_change(Change.modified, changed_file)

        watcher._debouncer.trigger.assert_awaited_once_with("proj-abc")

    @pytest.mark.asyncio
    @patch(f"{_WATCHER_MODULE}._query_known_projects", return_value=[])
    async def test_handle_change_new_directory(
        self, mock_query: MagicMock, tmp_path: Path
    ) -> None:
        """Adding a direct child directory (depth 1) under the projects
        root should refresh the cache and trigger a full scan."""
        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        new_dir = projects_root / "new-project"
        new_dir.mkdir()

        orch = _make_orchestrator()
        watcher = ProjectWatcher(orch)
        watcher._projects_root = projects_root.resolve()
        watcher._path_to_project_id = {}
        watcher._debouncer = MagicMock()
        watcher._debouncer.trigger = AsyncMock()

        await watcher._handle_change(Change.added, str(new_dir))

        # Let the asyncio.create_task for trigger_full_scan run
        await asyncio.sleep(0)

        orch.trigger_full_scan.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{_WATCHER_MODULE}._query_known_projects", return_value=[])
    async def test_handle_change_deleted_directory(
        self, mock_query: MagicMock, tmp_path: Path
    ) -> None:
        """Deleting a direct child directory should refresh the cache
        and trigger a full scan."""
        projects_root = tmp_path / "projects"
        projects_root.mkdir()

        orch = _make_orchestrator()
        watcher = ProjectWatcher(orch)
        watcher._projects_root = projects_root.resolve()
        watcher._path_to_project_id = {}
        watcher._debouncer = MagicMock()
        watcher._debouncer.trigger = AsyncMock()

        # The directory may no longer exist on disk, but the path is
        # still relative to projects_root.
        deleted_dir = str(projects_root / "old-project")
        await watcher._handle_change(Change.deleted, deleted_dir)

        # Let the asyncio.create_task for trigger_full_scan run
        await asyncio.sleep(0)

        orch.trigger_full_scan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_change_unknown_project_ignored(
        self, tmp_path: Path
    ) -> None:
        """A file change inside a directory that is NOT in the project
        cache should be silently ignored — debouncer not triggered."""
        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        unknown_dir = projects_root / "mystery"
        unknown_dir.mkdir()

        orch = _make_orchestrator()
        watcher = ProjectWatcher(orch)
        watcher._projects_root = projects_root.resolve()
        watcher._path_to_project_id = {}  # empty cache — nothing known
        watcher._debouncer = MagicMock()
        watcher._debouncer.trigger = AsyncMock()

        changed_file = str(unknown_dir / "file.txt")
        await watcher._handle_change(Change.modified, changed_file)

        watcher._debouncer.trigger.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_change_outside_root_ignored(
        self, tmp_path: Path
    ) -> None:
        """A path that is outside the projects root entirely should be
        silently ignored — nothing called."""
        projects_root = tmp_path / "projects"
        projects_root.mkdir()

        orch = _make_orchestrator()
        watcher = ProjectWatcher(orch)
        watcher._projects_root = projects_root.resolve()
        watcher._path_to_project_id = {}
        watcher._debouncer = MagicMock()
        watcher._debouncer.trigger = AsyncMock()

        outside_path = str(tmp_path / "somewhere-else" / "file.txt")
        await watcher._handle_change(Change.modified, outside_path)

        watcher._debouncer.trigger.assert_not_awaited()
        orch.trigger_full_scan.assert_not_awaited()
        orch.trigger_incremental_scan.assert_not_awaited()


# ===========================================================================
# Tests — Debounce Callback
# ===========================================================================


class TestOnDebounce:
    """The ``_on_debounce`` callback wiring to the orchestrator."""

    @pytest.mark.asyncio
    async def test_on_debounce_triggers_incremental_scan(self) -> None:
        """When the debouncer fires for a project the watcher should
        invoke ``trigger_incremental_scan`` with that project ID."""
        orch = _make_orchestrator()
        watcher = ProjectWatcher(orch)

        await watcher._on_debounce("proj-123")

        orch.trigger_incremental_scan.assert_awaited_once_with("proj-123")


# ===========================================================================
# Tests — Stop When Dormant
# ===========================================================================


class TestStopDormant:
    """Graceful stop when the watcher was never started."""

    @pytest.mark.asyncio
    async def test_stop_when_dormant(self) -> None:
        """Calling ``stop()`` on a watcher that was never started
        (dormant) should not raise any exception."""
        orch = _make_orchestrator()
        watcher = ProjectWatcher(orch)

        # Should not raise
        await watcher.stop()
