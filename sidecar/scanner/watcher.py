"""File watcher for the Engram scanning pipeline.

Monitors the configured ``projects_root`` directory for filesystem
changes using ``watchfiles.awatch`` (Rust-based, async-native).  Each
detected change is resolved to a project ID via a cached path lookup
and routed through a per-project ``AsyncDebouncer`` (5-second window)
before triggering an incremental scan on the orchestrator.

Direct child additions/deletions (new or removed project directories)
bypass the debouncer and trigger a full discovery scan immediately.

If ``projects_root`` is not configured in the database the watcher
enters a dormant state — ``start()`` returns without launching any
background tasks.

Reference: ARCHITECTURE.md §8 — File Watching & Incremental Updates.
"""

import asyncio
import logging
from pathlib import Path

from watchfiles import Change, awatch

from scanner.orchestrator import (
    ScanOrchestrator,
    _query_known_projects,
    _read_projects_root,
)
from utils.debounce import AsyncDebouncer

_log = logging.getLogger(__name__)


class ProjectWatcher:
    """Watches the projects root directory and triggers scans on changes.

    The watcher uses ``watchfiles.awatch`` which provides a built-in
    1600ms debounce that batches OS events.  On top of that, the
    per-project ``AsyncDebouncer`` adds a 5-second quiet window so
    that bulk operations (e.g., ``npm install``) collapse into a
    single incremental scan.

    Lifecycle::

        watcher = ProjectWatcher(orchestrator)
        await watcher.start()   # reads config, launches background task
        # ... application runs ...
        await watcher.stop()    # signals awatch, cancels debouncer

    Attributes:
        _orchestrator: The scan orchestrator for triggering scans.
        _stop_event: Set to signal ``awatch`` to stop gracefully.
        _task: Background task running the watch loop.
        _debouncer: Per-project debouncer for file change events.
        _projects_root: Resolved path to the projects root directory.
        _path_to_project_id: Cache mapping resolved project directory
            paths to their ULID project IDs.
    """

    def __init__(self, orchestrator: ScanOrchestrator) -> None:
        """Initialize the project watcher.

        Args:
            orchestrator: The scan orchestrator instance used to trigger
                full and incremental scans.
        """
        self._orchestrator: ScanOrchestrator = orchestrator
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None
        self._debouncer: AsyncDebouncer | None = None
        self._projects_root: Path | None = None
        self._path_to_project_id: dict[str, str] = {}

    @staticmethod
    def _log_task_exception(task: asyncio.Task[None]) -> None:
        """Log unhandled exceptions from fire-and-forget scan tasks.

        Attached as a done callback so that exceptions are retrieved
        and logged instead of triggering the asyncio "exception was
        never retrieved" warning.

        Args:
            task: The completed asyncio task to inspect.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _log.error("Background scan task %s failed: %s", task.get_name(), exc)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start watching the projects root directory.

        Reads ``projects_root`` from the database and, if configured,
        populates the project path cache and launches the background
        watch loop.  If the config value is missing or the path is not
        a directory the watcher enters dormant state and returns
        without starting any tasks.
        """
        root_str = await asyncio.to_thread(_read_projects_root)
        if root_str is None:
            _log.warning("projects_root not configured — file watcher dormant")
            return

        resolved = Path(root_str).expanduser().resolve()
        if not resolved.is_dir():
            _log.warning(
                "projects_root is not a directory: %s — file watcher dormant",
                resolved,
            )
            return

        self._projects_root = resolved

        # Build initial path -> project_id cache
        known_projects = await asyncio.to_thread(_query_known_projects)
        self._path_to_project_id = {str(Path(kp.path).resolve()): kp.id for kp in known_projects}

        self._stop_event = asyncio.Event()
        self._debouncer = AsyncDebouncer(delay=5.0, callback=self._on_debounce)
        self._task = asyncio.create_task(self._watch_loop(), name="project-watcher")

        _log.info("File watcher started for %s", self._projects_root)

    async def stop(self) -> None:
        """Stop the file watcher and cancel all pending debounce timers.

        Signals the ``awatch`` iterator to stop via the stop event,
        cancels all pending debounce timers, and awaits the background
        task.  Safe to call even if the watcher was never started
        (dormant state).
        """
        if self._stop_event is None:
            return

        self._stop_event.set()

        if self._debouncer is not None:
            await self._debouncer.cancel_all()

        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        _log.info("File watcher stopped")

    # ------------------------------------------------------------------
    # Watch loop
    # ------------------------------------------------------------------

    async def _watch_loop(self) -> None:
        """Run the ``awatch`` iterator until the stop event is set.

        Iterates over batches of filesystem changes yielded by
        ``watchfiles.awatch`` and dispatches each change to
        ``_handle_change``.  If the loop crashes unexpectedly the
        exception is logged so it does not propagate silently.
        """
        assert self._projects_root is not None
        assert self._stop_event is not None

        try:
            async for changes in awatch(str(self._projects_root), stop_event=self._stop_event):
                for change_type, path in changes:
                    await self._handle_change(change_type, path)
        except Exception:
            _log.exception("File watcher loop crashed")

    # ------------------------------------------------------------------
    # Change handling
    # ------------------------------------------------------------------

    async def _handle_change(self, change_type: Change, path: str) -> None:
        """Route a single filesystem change to the appropriate action.

        Resolves the changed path to a project directory under the
        projects root.  Direct child additions/deletions trigger a
        full discovery scan.  Normal file changes within a known
        project are debounced and trigger an incremental scan.

        Args:
            change_type: The type of change (added, modified, deleted).
            path: Absolute filesystem path of the changed file or
                directory.
        """
        assert self._projects_root is not None

        resolved = Path(path).resolve()

        try:
            rel = resolved.relative_to(self._projects_root)
        except ValueError:
            # Path is outside the projects root — ignore
            return

        if not rel.parts:
            # The root itself changed — ignore
            return

        project_dir_name = rel.parts[0]
        project_dir = str(self._projects_root / project_dir_name)

        # Direct child addition/deletion → full discovery scan
        if len(rel.parts) == 1:
            if change_type == Change.added:
                _log.info("New project directory detected: %s", project_dir_name)
                await self._refresh_cache()
                task = asyncio.create_task(
                    self._orchestrator.trigger_full_scan(),
                    name=f"full-scan-new-{project_dir_name}",
                )
                task.add_done_callback(self._log_task_exception)
                return

            if change_type == Change.deleted:
                _log.info("Project directory removed: %s", project_dir_name)
                await self._refresh_cache()
                task = asyncio.create_task(
                    self._orchestrator.trigger_full_scan(),
                    name=f"full-scan-del-{project_dir_name}",
                )
                task.add_done_callback(self._log_task_exception)
                return

        # Normal file change — debounce per project
        project_id = self._path_to_project_id.get(project_dir)
        if project_id is None:
            # Unknown project — not yet tracked in the database
            return

        assert self._debouncer is not None
        await self._debouncer.trigger(project_id)

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    async def _refresh_cache(self) -> None:
        """Reload the project path cache from the database.

        Called after detecting a new or deleted project directory so
        that subsequent file changes within the project resolve
        correctly.
        """
        known = await asyncio.to_thread(_query_known_projects)
        self._path_to_project_id = {str(Path(kp.path).resolve()): kp.id for kp in known}

    # ------------------------------------------------------------------
    # Debounce callback
    # ------------------------------------------------------------------

    async def _on_debounce(self, project_id: str) -> None:
        """Handle a debounce timer firing for a project.

        Called by the ``AsyncDebouncer`` after 5 seconds of quiet for
        the given project.  Triggers an incremental scan at watcher
        priority.

        Args:
            project_id: ULID of the project whose debounce window
                elapsed.
        """
        _log.debug(
            "Debounce fired for project %s, triggering incremental scan",
            project_id,
        )
        await self._orchestrator.trigger_incremental_scan(project_id)
