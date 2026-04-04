"""Tests for the WebSocket event hub and real-time event broadcasting.

Covers the ``EventHub`` connection manager (connect, disconnect,
broadcast), the ``/api/ws`` WebSocket endpoint via Starlette
TestClient, scan orchestrator event emission through the hub, and
watcher event emission for new/deleted project directories.

All WebSocket connections in unit tests use ``MagicMock`` objects —
no real network I/O.  Integration tests use the Starlette TestClient
which runs WebSocket connections in a background thread.
"""

import asyncio
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path setup — mirrors conftest.py convention
# ---------------------------------------------------------------------------

_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from api.websocket import EventHub
from main import app
from scanner.orchestrator import ScanOrchestrator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ORCH_MODULE = "scanner.orchestrator"
_WATCHER_MODULE = "scanner.watcher"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_ws(name: str = "ws") -> MagicMock:
    """Create a mock WebSocket with async ``accept`` and ``send_json``.

    Args:
        name: A label for debugging purposes.

    Returns:
        A ``MagicMock`` mimicking a FastAPI ``WebSocket``.
    """
    ws = MagicMock(name=name)
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


def _make_orchestrator_mocks() -> MagicMock:
    """Create a mock ``ScanOrchestrator`` with async entry points."""
    orch = MagicMock()
    orch.trigger_full_scan = AsyncMock()
    orch.trigger_incremental_scan = AsyncMock()
    return orch


# ===========================================================================
# 1. EventHub Unit Tests (no network, mock WebSockets)
# ===========================================================================


class TestEventHub:
    """Unit tests for the ``EventHub`` connection manager."""

    @pytest.mark.asyncio
    async def test_connect_accepts_and_tracks(self) -> None:
        """connect() should call accept() on the websocket and add
        it to the active connections list."""
        hub = EventHub()
        ws = _make_mock_ws("client-1")

        await hub.connect(ws)

        ws.accept.assert_awaited_once()
        assert ws in hub.active_connections
        assert len(hub.active_connections) == 1

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self) -> None:
        """disconnect() should remove a previously connected websocket
        from the active connections list."""
        hub = EventHub()
        ws = _make_mock_ws("client-1")
        await hub.connect(ws)

        hub.disconnect(ws)

        assert ws not in hub.active_connections
        assert len(hub.active_connections) == 0

    @pytest.mark.asyncio
    async def test_disconnect_idempotent(self) -> None:
        """Calling disconnect() twice for the same websocket should
        not raise an error — the second call is a no-op."""
        hub = EventHub()
        ws = _make_mock_ws("client-1")
        await hub.connect(ws)

        hub.disconnect(ws)
        hub.disconnect(ws)  # Should not raise

        assert ws not in hub.active_connections

    @pytest.mark.asyncio
    async def test_disconnect_untracked_websocket(self) -> None:
        """Calling disconnect() with a websocket that was never
        connected should not raise an error."""
        hub = EventHub()
        ws = _make_mock_ws("never-connected")

        hub.disconnect(ws)  # Should not raise

        assert len(hub.active_connections) == 0

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_clients(self) -> None:
        """broadcast() should send the structured JSON message to
        every connected client."""
        hub = EventHub()
        ws1 = _make_mock_ws("client-1")
        ws2 = _make_mock_ws("client-2")
        ws3 = _make_mock_ws("client-3")

        await hub.connect(ws1)
        await hub.connect(ws2)
        await hub.connect(ws3)

        await hub.broadcast(
            "scan_progress", {"phase": "edges", "current": 0, "total": 0}
        )

        expected_message = {
            "event": "scan_progress",
            "data": {"phase": "edges", "current": 0, "total": 0},
        }
        ws1.send_json.assert_awaited_once_with(expected_message)
        ws2.send_json.assert_awaited_once_with(expected_message)
        ws3.send_json.assert_awaited_once_with(expected_message)

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connection(self) -> None:
        """When a client's send_json raises an exception, that client
        should be removed from active connections while the remaining
        clients still receive the message."""
        hub = EventHub()
        ws1 = _make_mock_ws("client-1")
        ws2 = _make_mock_ws("client-2-dead")
        ws3 = _make_mock_ws("client-3")

        await hub.connect(ws1)
        await hub.connect(ws2)
        await hub.connect(ws3)

        # Make the second client's send_json fail
        ws2.send_json = AsyncMock(side_effect=RuntimeError("connection lost"))

        await hub.broadcast(
            "project_updated", {"id": "proj-123", "fields": ["git_branch"]}
        )

        expected_message = {
            "event": "project_updated",
            "data": {"id": "proj-123", "fields": ["git_branch"]},
        }
        ws1.send_json.assert_awaited_once_with(expected_message)
        ws3.send_json.assert_awaited_once_with(expected_message)

        # Dead client should have been removed
        assert ws2 not in hub.active_connections
        assert len(hub.active_connections) == 2

    @pytest.mark.asyncio
    async def test_broadcast_noop_when_empty(self) -> None:
        """broadcast() with no connected clients should complete
        without any errors."""
        hub = EventHub()

        # Should not raise
        await hub.broadcast(
            "scan_completed", {"duration_ms": 1234, "projects_scanned": 5}
        )

    @pytest.mark.asyncio
    async def test_broadcast_message_structure(self) -> None:
        """The broadcast message should always have exactly the
        'event' and 'data' keys."""
        hub = EventHub()
        ws = _make_mock_ws("client-1")
        await hub.connect(ws)

        await hub.broadcast("new_project_detected", {"path": "/tmp/proj", "name": "proj"})

        sent_message = ws.send_json.call_args[0][0]
        assert set(sent_message.keys()) == {"event", "data"}
        assert sent_message["event"] == "new_project_detected"
        assert sent_message["data"] == {"path": "/tmp/proj", "name": "proj"}

    @pytest.mark.asyncio
    async def test_broadcast_all_dead_connections(self) -> None:
        """When all connected clients are dead, broadcast should
        remove all of them and leave active_connections empty."""
        hub = EventHub()
        ws1 = _make_mock_ws("dead-1")
        ws2 = _make_mock_ws("dead-2")

        await hub.connect(ws1)
        await hub.connect(ws2)

        ws1.send_json = AsyncMock(side_effect=RuntimeError("dead"))
        ws2.send_json = AsyncMock(side_effect=RuntimeError("dead"))

        await hub.broadcast("scan_progress", {"phase": "discovery", "current": 0, "total": 0})

        assert len(hub.active_connections) == 0

    @pytest.mark.asyncio
    async def test_multiple_connects(self) -> None:
        """Connecting multiple websockets should track all of them."""
        hub = EventHub()
        clients = [_make_mock_ws(f"client-{i}") for i in range(5)]

        for ws in clients:
            await hub.connect(ws)

        assert len(hub.active_connections) == 5
        for ws in clients:
            assert ws in hub.active_connections


# ===========================================================================
# 2. WebSocket Endpoint Integration Tests (Starlette TestClient)
# ===========================================================================


class TestWebSocketEndpoint:
    """Integration tests for the ``/api/ws`` WebSocket endpoint."""

    def test_websocket_connect_and_disconnect(self, client: Any) -> None:
        """A client should be able to connect to /api/ws and cleanly
        disconnect without errors."""
        with client.websocket_connect("/api/ws") as ws:
            # Connection is accepted — no exception raised
            assert ws is not None

        # After context manager exit, the connection is closed cleanly

    def test_websocket_receives_broadcast(self, client: Any) -> None:
        """A connected client should receive messages broadcast
        through the EventHub on app.state."""
        with client.websocket_connect("/api/ws") as ws:
            hub = app.state.event_hub

            # Broadcast from a separate thread since the websocket
            # receive loop is running in the TestClient background thread
            def send_broadcast() -> None:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    hub.broadcast(
                        "scan_progress",
                        {"phase": "analyzing", "current": 1, "total": 5},
                    )
                )
                loop.close()

            t = threading.Thread(target=send_broadcast)
            t.start()
            t.join(timeout=5)

            data = ws.receive_json()
            assert data["event"] == "scan_progress"
            assert data["data"]["phase"] == "analyzing"
            assert data["data"]["current"] == 1
            assert data["data"]["total"] == 5

    def test_multi_client_connect(self, client: Any) -> None:
        """Multiple clients should be able to connect simultaneously
        and all be tracked by the EventHub."""
        with client.websocket_connect("/api/ws") as ws1:
            with client.websocket_connect("/api/ws") as ws2:
                hub = app.state.event_hub
                assert len(hub.active_connections) >= 2

    def test_websocket_receives_multiple_events(self, client: Any) -> None:
        """A connected client should receive multiple sequential
        broadcast messages in order."""
        with client.websocket_connect("/api/ws") as ws:
            hub = app.state.event_hub

            events = [
                ("scan_progress", {"phase": "discovery", "current": 0, "total": 0}),
                ("scan_progress", {"phase": "analyzing", "current": 0, "total": 3}),
                ("scan_completed", {"duration_ms": 500, "projects_scanned": 3}),
            ]

            def send_broadcasts() -> None:
                loop = asyncio.new_event_loop()
                for event, data in events:
                    loop.run_until_complete(hub.broadcast(event, data))
                loop.close()

            t = threading.Thread(target=send_broadcasts)
            t.start()
            t.join(timeout=5)

            for event, data in events:
                received = ws.receive_json()
                assert received["event"] == event
                assert received["data"] == data


# ===========================================================================
# 3. Orchestrator Event Emission Tests
# ===========================================================================


class TestOrchestratorEvents:
    """Verify that the scan orchestrator broadcasts the correct events
    through the EventHub at each pipeline phase."""

    @pytest.mark.asyncio
    @patch(f"{_ORCH_MODULE}._run_edge_computation")
    @patch(f"{_ORCH_MODULE}._update_missing_flags")
    @patch(f"{_ORCH_MODULE}.discover")
    @patch(f"{_ORCH_MODULE}._query_known_projects")
    @patch(f"{_ORCH_MODULE}._read_projects_root")
    async def test_full_scan_emits_scan_progress_and_completed(
        self,
        mock_read: MagicMock,
        mock_query: MagicMock,
        mock_discover: MagicMock,
        mock_update: MagicMock,
        mock_edges: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A full scan should broadcast scan_progress events for each
        phase (discovery, analyzing, edges) and a scan_completed event
        at the end."""
        from scanner.discovery import DiscoveryResult
        from scanner.edge_computer import EdgeComputationResult

        projects_root = tmp_path / "projects"
        projects_root.mkdir()

        mock_read.return_value = str(projects_root)
        mock_query.return_value = []
        mock_discover.return_value = DiscoveryResult(
            new=[], missing=[], existing=[], projects_root=str(projects_root)
        )
        mock_update.return_value = None
        mock_edges.return_value = EdgeComputationResult(
            created=0, updated=0, deleted=0, unchanged=0
        )

        mock_hub = MagicMock()
        mock_hub.broadcast = AsyncMock()

        orch = ScanOrchestrator(event_hub=mock_hub)
        await orch.trigger_full_scan()

        # Collect all broadcast calls
        broadcast_calls = mock_hub.broadcast.call_args_list

        # Extract event names
        event_names = [c[0][0] for c in broadcast_calls]

        # Must have scan_progress for discovery, analyzing, edges
        assert "scan_progress" in event_names
        assert "scan_completed" in event_names

        # Verify phase progression within scan_progress events
        progress_phases = [
            c[0][1]["phase"]
            for c in broadcast_calls
            if c[0][0] == "scan_progress"
        ]
        assert "discovery" in progress_phases
        assert "analyzing" in progress_phases
        assert "edges" in progress_phases

        # Verify scan_completed has expected keys
        completed_call = [
            c for c in broadcast_calls if c[0][0] == "scan_completed"
        ]
        assert len(completed_call) == 1
        completed_data = completed_call[0][0][1]
        assert "duration_ms" in completed_data
        assert "projects_scanned" in completed_data
        assert isinstance(completed_data["duration_ms"], int)
        assert completed_data["projects_scanned"] == 0

    @pytest.mark.asyncio
    @patch(f"{_ORCH_MODULE}._run_edge_computation")
    @patch(f"{_ORCH_MODULE}._update_missing_flags")
    @patch(f"{_ORCH_MODULE}.discover")
    @patch(f"{_ORCH_MODULE}._query_known_projects")
    @patch(f"{_ORCH_MODULE}._read_projects_root")
    async def test_full_scan_with_projects_emits_per_project_progress(
        self,
        mock_read: MagicMock,
        mock_query: MagicMock,
        mock_discover: MagicMock,
        mock_update: MagicMock,
        mock_edges: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When projects exist, the analyzing phase should emit
        scan_progress events with incrementing current counts."""
        from scanner.discovery import DiscoveryResult, KnownProject
        from scanner.edge_computer import EdgeComputationResult

        projects_root = tmp_path / "projects"
        projects_root.mkdir()

        # Create 2 project directories
        proj_dirs = []
        known = []
        for i in range(2):
            d = projects_root / f"proj-{i}"
            d.mkdir()
            proj_dirs.append(d)
            known.append(KnownProject(id=f"id-{i}", name=f"proj-{i}", path=str(d)))

        mock_read.return_value = str(projects_root)
        mock_query.return_value = known
        mock_discover.return_value = DiscoveryResult(
            new=[], missing=[], existing=known, projects_root=str(projects_root)
        )
        mock_update.return_value = None
        mock_edges.return_value = EdgeComputationResult(
            created=0, updated=0, deleted=0, unchanged=0
        )

        mock_hub = MagicMock()
        mock_hub.broadcast = AsyncMock()

        orch = ScanOrchestrator(event_hub=mock_hub)

        # Mock _analyze_project to be a no-op (avoids real analyzer calls)
        orch._analyze_project = AsyncMock()  # type: ignore[method-assign]

        await orch.trigger_full_scan()

        broadcast_calls = mock_hub.broadcast.call_args_list

        # Find all analyzing-phase progress events
        analyzing_progress = [
            c[0][1]
            for c in broadcast_calls
            if c[0][0] == "scan_progress" and c[0][1].get("phase") == "analyzing"
        ]

        # Should have initial (current=0) + per-project updates
        assert len(analyzing_progress) >= 1
        assert analyzing_progress[0]["total"] == 2

    @pytest.mark.asyncio
    async def test_analyze_project_emits_project_updated(
        self, tmp_path: Path
    ) -> None:
        """When _persist_results returns changed fields, _analyze_project
        should broadcast a project_updated event with those fields."""
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()

        mock_hub = MagicMock()
        mock_hub.broadcast = AsyncMock()

        orch = ScanOrchestrator(event_hub=mock_hub)

        # Mock _run_analyzers to return dummy results
        orch._run_analyzers = AsyncMock(return_value={})  # type: ignore[method-assign]

        # Mock _persist_results to return changed fields
        orch._persist_results = MagicMock(  # type: ignore[method-assign]
            return_value=["git_branch", "git_dirty"]
        )

        await orch._analyze_project("proj_123", str(project_dir))

        mock_hub.broadcast.assert_awaited_once_with(
            "project_updated",
            {"id": "proj_123", "fields": ["git_branch", "git_dirty"]},
        )

    @pytest.mark.asyncio
    async def test_analyze_project_skips_broadcast_when_no_changes(
        self, tmp_path: Path
    ) -> None:
        """When _persist_results returns an empty list, no
        project_updated event should be broadcast."""
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()

        mock_hub = MagicMock()
        mock_hub.broadcast = AsyncMock()

        orch = ScanOrchestrator(event_hub=mock_hub)

        # Mock _run_analyzers to return dummy results
        orch._run_analyzers = AsyncMock(return_value={})  # type: ignore[method-assign]

        # Mock _persist_results to return no changes
        orch._persist_results = MagicMock(return_value=[])  # type: ignore[method-assign]

        await orch._analyze_project("proj_456", str(project_dir))

        # broadcast should NOT have been called with "project_updated"
        mock_hub.broadcast.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_orchestrator_works_without_event_hub(self) -> None:
        """Creating an orchestrator without an event hub and calling
        _broadcast should not raise any errors."""
        orch = ScanOrchestrator()  # No event_hub

        # Should not raise
        await orch._broadcast("scan_progress", {"phase": "test", "current": 0, "total": 0})

    @pytest.mark.asyncio
    async def test_analyze_project_skips_missing_directory(self) -> None:
        """When the project directory does not exist, _analyze_project
        should return early without calling _run_analyzers or
        broadcasting."""
        mock_hub = MagicMock()
        mock_hub.broadcast = AsyncMock()

        orch = ScanOrchestrator(event_hub=mock_hub)
        orch._run_analyzers = AsyncMock()  # type: ignore[method-assign]

        # Path that does not exist
        await orch._analyze_project("proj_789", "/nonexistent/path")

        orch._run_analyzers.assert_not_awaited()
        mock_hub.broadcast.assert_not_awaited()


# ===========================================================================
# 4. Watcher Event Emission Tests
# ===========================================================================


class TestWatcherEvents:
    """Verify that the file watcher broadcasts the correct events
    for new and deleted project directories."""

    @pytest.mark.asyncio
    @patch(f"{_WATCHER_MODULE}._query_known_projects", return_value=[])
    async def test_new_project_broadcasts_event(
        self, mock_query: MagicMock, tmp_path: Path
    ) -> None:
        """When a new directory is added at depth 1 under projects_root,
        the watcher should broadcast a new_project_detected event."""
        from scanner.watcher import ProjectWatcher
        from watchfiles import Change

        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        new_dir = projects_root / "newproject"
        new_dir.mkdir()

        mock_hub = MagicMock()
        mock_hub.broadcast = AsyncMock()

        orch = _make_orchestrator_mocks()
        watcher = ProjectWatcher(orch, event_hub=mock_hub)
        watcher._projects_root = projects_root.resolve()
        watcher._path_to_project_id = {}
        watcher._debouncer = MagicMock()
        watcher._debouncer.trigger = AsyncMock()

        await watcher._handle_change(Change.added, str(new_dir))

        # Let the asyncio.create_task for trigger_full_scan run
        await asyncio.sleep(0)

        mock_hub.broadcast.assert_awaited_once_with(
            "new_project_detected",
            {
                "path": str(projects_root.resolve() / "newproject"),
                "name": "newproject",
            },
        )

    @pytest.mark.asyncio
    @patch(f"{_WATCHER_MODULE}._query_known_projects", return_value=[])
    async def test_deleted_project_broadcasts_event(
        self, mock_query: MagicMock, tmp_path: Path
    ) -> None:
        """When a directory is deleted at depth 1, the watcher should
        broadcast a project_missing event if the project ID is known."""
        from scanner.watcher import ProjectWatcher
        from watchfiles import Change

        projects_root = tmp_path / "projects"
        projects_root.mkdir()

        deleted_dir = str(projects_root.resolve() / "old-project")

        mock_hub = MagicMock()
        mock_hub.broadcast = AsyncMock()

        orch = _make_orchestrator_mocks()
        watcher = ProjectWatcher(orch, event_hub=mock_hub)
        watcher._projects_root = projects_root.resolve()
        watcher._path_to_project_id = {
            deleted_dir: "proj-old-123",
        }
        watcher._debouncer = MagicMock()
        watcher._debouncer.trigger = AsyncMock()

        await watcher._handle_change(Change.deleted, deleted_dir)

        # Let the asyncio.create_task for trigger_full_scan run
        await asyncio.sleep(0)

        mock_hub.broadcast.assert_awaited_once_with(
            "project_missing",
            {
                "id": "proj-old-123",
                "path": deleted_dir,
            },
        )

    @pytest.mark.asyncio
    @patch(f"{_WATCHER_MODULE}._query_known_projects", return_value=[])
    async def test_deleted_project_no_broadcast_when_id_unknown(
        self, mock_query: MagicMock, tmp_path: Path
    ) -> None:
        """When a directory is deleted at depth 1 but the project ID
        is not in the cache, no project_missing event should be
        broadcast (though a full scan is still triggered)."""
        from scanner.watcher import ProjectWatcher
        from watchfiles import Change

        projects_root = tmp_path / "projects"
        projects_root.mkdir()

        deleted_dir = str(projects_root.resolve() / "unknown-project")

        mock_hub = MagicMock()
        mock_hub.broadcast = AsyncMock()

        orch = _make_orchestrator_mocks()
        watcher = ProjectWatcher(orch, event_hub=mock_hub)
        watcher._projects_root = projects_root.resolve()
        watcher._path_to_project_id = {}  # Empty cache — ID not known
        watcher._debouncer = MagicMock()
        watcher._debouncer.trigger = AsyncMock()

        await watcher._handle_change(Change.deleted, deleted_dir)

        # Let the asyncio.create_task for trigger_full_scan run
        await asyncio.sleep(0)

        # No broadcast because the project ID was not found in cache
        mock_hub.broadcast.assert_not_awaited()

        # But full scan should still have been triggered
        orch.trigger_full_scan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_watcher_works_without_event_hub(
        self, tmp_path: Path
    ) -> None:
        """Creating a watcher without an event hub and triggering a
        change should not raise any errors."""
        from scanner.watcher import ProjectWatcher

        orch = _make_orchestrator_mocks()
        watcher = ProjectWatcher(orch)  # No event_hub

        # _broadcast should be a no-op
        await watcher._broadcast("test_event", {"key": "value"})

    @pytest.mark.asyncio
    async def test_watcher_broadcast_noop_without_hub(self) -> None:
        """The watcher's _broadcast method should be a silent no-op
        when event_hub is None."""
        from scanner.watcher import ProjectWatcher

        orch = _make_orchestrator_mocks()
        watcher = ProjectWatcher(orch)

        # Should not raise — _event_hub is None
        await watcher._broadcast(
            "new_project_detected", {"path": "/tmp/proj", "name": "proj"}
        )

    @pytest.mark.asyncio
    @patch(f"{_WATCHER_MODULE}._query_known_projects", return_value=[])
    async def test_file_change_in_known_project_does_not_broadcast(
        self, mock_query: MagicMock, tmp_path: Path
    ) -> None:
        """A file modification inside a known project should trigger
        the debouncer but should NOT broadcast any event directly."""
        from scanner.watcher import ProjectWatcher
        from watchfiles import Change

        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        project_dir = projects_root / "myproject"
        project_dir.mkdir()

        mock_hub = MagicMock()
        mock_hub.broadcast = AsyncMock()

        orch = _make_orchestrator_mocks()
        watcher = ProjectWatcher(orch, event_hub=mock_hub)
        watcher._projects_root = projects_root.resolve()
        watcher._path_to_project_id = {
            str(project_dir.resolve()): "proj-known",
        }
        watcher._debouncer = MagicMock()
        watcher._debouncer.trigger = AsyncMock()

        changed_file = str(project_dir / "src" / "main.py")
        await watcher._handle_change(Change.modified, changed_file)

        # Debouncer should have been triggered
        watcher._debouncer.trigger.assert_awaited_once_with("proj-known")

        # But no broadcast should have been made
        mock_hub.broadcast.assert_not_awaited()
