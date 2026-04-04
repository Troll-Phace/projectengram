"""Scan orchestrator for the Engram scanning pipeline.

Wires together discovery, six per-project analyzers, and edge
computation into a unified pipeline with three layers of concurrency
control:

1. ``asyncio.PriorityQueue`` for job ordering (full=0, manual=5,
   watcher=10).
2. ``asyncio.Semaphore(4)`` for limiting concurrent project scans.
3. Per-project ``asyncio.Lock`` to prevent double-writes.

The orchestrator exposes three entry points:

* ``trigger_full_scan()`` — runs the complete discovery-analyze-edges
  pipeline, bypassing the queue.
* ``trigger_manual_rescan(project_id)`` — enqueues a single project
  at manual priority.
* ``trigger_incremental_scan(project_id)`` — enqueues a single project
  at watcher priority (lowest).

Workers consume ``ScanJob`` items from the priority queue and call the
analyzer pipeline for each project.

Reference: ARCHITECTURE.md §9 — Scan Concurrency.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from api.websocket import EventHub

from sqlmodel import Session, select

from db.engine import engine
from models import Config, Project
from scanner.analyzers.frameworks import FrameworkDetectionResult, detect_frameworks
from scanner.analyzers.git_analyzer import GitAnalysisResult, analyze_git
from scanner.analyzers.languages import LanguageBreakdownResult, analyze_languages
from scanner.analyzers.project_type import ProjectTypeResult, detect_project_type
from scanner.analyzers.readme import ReadmeResult, extract_readme
from scanner.analyzers.size import SizeResult, compute_size
from scanner.discovery import KnownProject, discover
from scanner.edge_computer import EdgeComputationResult, compute_edges
from utils.time import now_iso

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRIORITY_FULL: int = 0
"""Priority for jobs created during a full scan."""

PRIORITY_MANUAL: int = 5
"""Priority for manually triggered project rescans."""

PRIORITY_WATCHER: int = 10
"""Priority for watcher-triggered incremental scans."""

MAX_CONCURRENT: int = 4
"""Maximum number of projects analyzed concurrently."""

_TRACKED_FIELDS: list[str] = [
    "package_manager",
    "frameworks",
    "languages",
    "primary_language",
    "loc",
    "file_count",
    "git_branch",
    "git_dirty",
    "git_last_commit_hash",
    "git_last_commit_date",
    "git_last_commit_msg",
    "git_branch_count",
    "git_remote_url",
    "description",
    "size_bytes",
]
"""Project model fields tracked for change-detection during persist."""

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class ScanStatus(str, Enum):
    """Current state of the scan orchestrator."""

    IDLE = "idle"
    SCANNING = "scanning"


@dataclass
class ScanProgress:
    """Mutable progress tracker exposed via the status endpoint.

    Attributes:
        status: Whether the orchestrator is idle or actively scanning.
        phase: Current pipeline phase name, or ``None`` when idle.
        total: Total number of projects to analyze in this scan.
        completed: Number of projects that have finished analysis.
        errors: Number of projects that failed during analysis.
    """

    status: ScanStatus = ScanStatus.IDLE
    phase: str | None = None
    total: int = 0
    completed: int = 0
    errors: int = 0


@dataclass(order=True)
class ScanJob:
    """A unit of work for the priority queue.

    Ordering uses ``(priority, sequence)`` so that lower-priority
    values run first and FIFO order is maintained within the same
    priority tier.

    Attributes:
        priority: Job priority (0=full, 5=manual, 10=watcher).
        sequence: Monotonic tiebreaker for FIFO within same priority.
        project_id: ULID of the project to scan.
        project_path: Absolute filesystem path to the project directory.
        is_sentinel: When True, signals a worker to shut down.
    """

    priority: int
    sequence: int
    project_id: str = field(compare=False)
    project_path: str = field(compare=False)
    is_sentinel: bool = field(default=False, compare=False)


# ---------------------------------------------------------------------------
# Default / fallback result factories
# ---------------------------------------------------------------------------


def _empty_project_type() -> ProjectTypeResult:
    """Return a safe empty ``ProjectTypeResult`` for error fallback."""
    return ProjectTypeResult(
        primary_manifest=None,
        manifests=[],
        project_name=None,
        description=None,
        all_dependencies=frozenset(),
        package_manager=None,
    )


def _empty_framework() -> FrameworkDetectionResult:
    """Return a safe empty ``FrameworkDetectionResult`` for error fallback."""
    return FrameworkDetectionResult(frameworks=[])


def _empty_languages() -> LanguageBreakdownResult:
    """Return a safe empty ``LanguageBreakdownResult`` for error fallback."""
    return LanguageBreakdownResult(
        primary_language=None,
        language_percentages={},
        lines_by_language={},
        total_loc=0,
        file_count=0,
    )


def _empty_git() -> GitAnalysisResult:
    """Return a safe empty ``GitAnalysisResult`` for error fallback."""
    return GitAnalysisResult(
        is_git_repo=False,
        branch=None,
        dirty=False,
        last_commit_hash=None,
        last_commit_date=None,
        last_commit_msg=None,
        branch_count=None,
        remote_url=None,
    )


def _empty_readme() -> ReadmeResult:
    """Return a safe empty ``ReadmeResult`` for error fallback."""
    return ReadmeResult(snippet=None, source=None)


def _empty_size() -> SizeResult:
    """Return a safe empty ``SizeResult`` for error fallback."""
    return SizeResult(size_bytes=0, file_count=0, source_file_count=0)


# ---------------------------------------------------------------------------
# Thread-safe DB helpers (called via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _read_projects_root() -> str | None:
    """Read the ``projects_root`` config value from the database.

    Returns:
        The resolved projects root path string, or ``None`` if not
        configured.
    """
    with Session(engine) as session:
        cfg = session.exec(
            select(Config).where(Config.key == "projects_root")
        ).first()
        if cfg is None or cfg.value is None:
            return None
        try:
            parsed = json.loads(cfg.value)
            return parsed if isinstance(parsed, str) else cfg.value
        except (json.JSONDecodeError, TypeError, ValueError):
            return cfg.value


def _query_known_projects() -> list[KnownProject]:
    """Query all non-deleted projects that have a path.

    Returns:
        A list of lightweight ``KnownProject`` projections.
    """
    with Session(engine) as session:
        rows = session.exec(
            select(Project).where(
                Project.deleted_at.is_(None),  # type: ignore[union-attr]
                Project.path.isnot(None),  # type: ignore[union-attr]
            )
        ).all()
        return [
            KnownProject(id=p.id, name=p.name, path=p.path)  # type: ignore[arg-type]
            for p in rows
        ]


def _update_missing_flags(
    missing_ids: list[str],
    existing_ids: list[str],
) -> None:
    """Mark missing projects and clear the flag on existing ones.

    Args:
        missing_ids: Project IDs whose directories are no longer on disk.
        existing_ids: Project IDs whose directories still exist.
    """
    with Session(engine) as session:
        now = now_iso()
        for mid in missing_ids:
            proj = session.get(Project, mid)
            if proj is not None:
                proj.missing = True
                proj.updated_at = now
                session.add(proj)
        for eid in existing_ids:
            proj = session.get(Project, eid)
            if proj is not None and proj.missing:
                proj.missing = False
                proj.updated_at = now
                session.add(proj)
        session.commit()


def _lookup_project_path(project_id: str) -> str | None:
    """Look up a single project's path from the database.

    Args:
        project_id: ULID of the project.

    Returns:
        The project's filesystem path, or ``None`` if not found.
    """
    with Session(engine) as session:
        proj = session.get(Project, project_id)
        if proj is None or proj.path is None:
            return None
        return proj.path


def _run_edge_computation() -> EdgeComputationResult:
    """Run the edge computation engine in a fresh session.

    Returns:
        An ``EdgeComputationResult`` with counts of created, updated,
        deleted, and unchanged edges.
    """
    with Session(engine) as session:
        projects = session.exec(
            select(Project).where(
                Project.deleted_at.is_(None),  # type: ignore[union-attr]
                Project.path.isnot(None),  # type: ignore[union-attr]
            )
        ).all()
        return compute_edges(session, list(projects))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ScanOrchestrator:
    """Coordinates the full scanning pipeline with concurrency control.

    The orchestrator manages worker tasks that consume from a priority
    queue, a semaphore that limits concurrent analyzer invocations, and
    per-project locks that prevent double-writes to the same row.

    Typical lifecycle::

        orchestrator = ScanOrchestrator()
        await orchestrator.start()
        await orchestrator.trigger_full_scan()
        # ... later ...
        await orchestrator.shutdown()
    """

    def __init__(self, event_hub: "EventHub | None" = None) -> None:
        """Initialise the scan orchestrator.

        Args:
            event_hub: Optional WebSocket event hub for broadcasting
                scan progress and project update events.  When ``None``
                (the default), all broadcast calls are silently skipped,
                which is useful for testing.
        """
        self._queue: asyncio.PriorityQueue[ScanJob] = asyncio.PriorityQueue()
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._project_locks: dict[str, asyncio.Lock] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._progress: ScanProgress = ScanProgress()
        self._full_scan_lock: asyncio.Lock = asyncio.Lock()
        self._shutdown: bool = False
        self._seq: int = 0
        self._event_hub = event_hub

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        """Return next monotonic sequence number for FIFO tiebreaking.

        Returns:
            An incrementing integer.
        """
        self._seq += 1
        return self._seq

    def _get_project_lock(self, project_id: str) -> asyncio.Lock:
        """Get or create a per-project lock.

        Args:
            project_id: ULID of the project.

        Returns:
            The ``asyncio.Lock`` associated with this project.
        """
        if project_id not in self._project_locks:
            self._project_locks[project_id] = asyncio.Lock()
        return self._project_locks[project_id]

    def get_status(self) -> ScanProgress:
        """Return current scan progress.

        Returns:
            A ``ScanProgress`` dataclass with current pipeline state.
        """
        return self._progress

    async def _broadcast(self, event: str, data: dict[str, Any]) -> None:
        """Broadcast an event via the WebSocket hub, if available.

        No-op when ``event_hub`` was not provided (e.g. in tests).

        Args:
            event: Event type string.
            data: Event payload dictionary.
        """
        if self._event_hub is not None:
            await self._event_hub.broadcast(event, data)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spawn worker tasks that consume from the priority queue.

        Creates ``MAX_CONCURRENT`` worker coroutines as background
        tasks.  Must be called once before enqueuing any jobs.
        """
        _log.info("Starting %d scan workers", MAX_CONCURRENT)
        for worker_id in range(MAX_CONCURRENT):
            task = asyncio.create_task(
                self._worker(worker_id),
                name=f"scan-worker-{worker_id}",
            )
            self._workers.append(task)

    async def shutdown(self) -> None:
        """Gracefully shut down all worker tasks.

        Enqueues sentinel jobs (one per worker) so each worker breaks
        out of its consumption loop, then awaits all worker tasks.
        """
        _log.info("Shutting down scan orchestrator")
        self._shutdown = True
        for _ in range(len(self._workers)):
            sentinel = ScanJob(
                priority=0,
                sequence=self._next_seq(),
                project_id="",
                project_path="",
                is_sentinel=True,
            )
            await self._queue.put(sentinel)
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._project_locks.clear()
        _log.info("Scan orchestrator shut down")

    # ------------------------------------------------------------------
    # Triggers
    # ------------------------------------------------------------------

    async def trigger_full_scan(self) -> None:
        """Run the complete discovery-analyze-edges pipeline.

        This method bypasses the priority queue and manages its own
        concurrency via the shared semaphore.  Only one full scan can
        run at a time; concurrent calls are dropped with a warning.

        The pipeline has three phases:

        1. **Discovery** — enumerate project directories and diff
           against known DB projects.
        2. **Analyzing** — run all six analyzers on each existing
           project, limited by the semaphore.
        3. **Edges** — compute pairwise auto-edges for all projects.
        """
        if self._full_scan_lock.locked():
            _log.warning("Full scan already in progress, skipping")
            return

        async with self._full_scan_lock:
            try:
                await self._execute_full_scan()
            except Exception:
                _log.exception("Full scan failed unexpectedly")
            finally:
                self._progress = ScanProgress()

    async def _execute_full_scan(self) -> None:
        """Internal implementation of the full scan pipeline.

        Separated from ``trigger_full_scan`` so that the lock and
        progress reset live in the caller.
        """
        start_time = time.monotonic()

        # Phase 1: Discovery -------------------------------------------
        self._progress = ScanProgress(
            status=ScanStatus.SCANNING, phase="discovery"
        )
        await self._broadcast(
            "scan_progress", {"phase": "discovery", "current": 0, "total": 0}
        )

        root_str = await asyncio.to_thread(_read_projects_root)
        if root_str is None:
            _log.warning("projects_root not configured, skipping full scan")
            return

        resolved_root = Path(root_str).expanduser().resolve()
        if not resolved_root.is_dir():
            _log.warning(
                "projects_root is not a directory: %s", resolved_root
            )
            return

        known_projects = await asyncio.to_thread(_query_known_projects)
        discovery_result = await asyncio.to_thread(
            discover, resolved_root, known_projects
        )

        _log.info(
            "Discovery: new=%d, missing=%d, existing=%d",
            len(discovery_result.new),
            len(discovery_result.missing),
            len(discovery_result.existing),
        )

        # Update missing flags -----------------------------------------
        missing_ids = [kp.id for kp in discovery_result.missing]
        existing_ids = [kp.id for kp in discovery_result.existing]
        if missing_ids or existing_ids:
            await asyncio.to_thread(
                _update_missing_flags, missing_ids, existing_ids
            )

        # Phase 2: Analyzing -------------------------------------------
        existing = discovery_result.existing
        self._progress.phase = "analyzing"
        self._progress.total = len(existing)
        self._progress.completed = 0
        self._progress.errors = 0
        await self._broadcast(
            "scan_progress",
            {"phase": "analyzing", "current": 0, "total": len(existing)},
        )

        async def _analyze_with_semaphore(
            project_id: str, project_path: str
        ) -> None:
            """Run analysis for one project under the semaphore."""
            async with self._semaphore:
                await self._analyze_project(project_id, project_path)
            self._progress.completed += 1
            await self._broadcast(
                "scan_progress",
                {
                    "phase": "analyzing",
                    "current": self._progress.completed,
                    "total": self._progress.total,
                },
            )

        tasks = [
            _analyze_with_semaphore(kp.id, kp.path)
            for kp in existing
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                self._progress.errors += 1
                _log.exception(
                    "Analyzer failed for project %s",
                    existing[i].id,
                    exc_info=result,
                )

        # Phase 3: Edge computation ------------------------------------
        self._progress.phase = "edges"
        await self._broadcast(
            "scan_progress", {"phase": "edges", "current": 0, "total": 0}
        )
        try:
            edge_result = await asyncio.to_thread(_run_edge_computation)
            _log.info(
                "Edge computation: created=%d, updated=%d, "
                "deleted=%d, unchanged=%d",
                edge_result.created,
                edge_result.updated,
                edge_result.deleted,
                edge_result.unchanged,
            )
        except Exception:
            _log.exception("Edge computation failed")

        duration_ms = int((time.monotonic() - start_time) * 1000)
        await self._broadcast(
            "scan_completed",
            {
                "duration_ms": duration_ms,
                "projects_scanned": len(existing),
            },
        )

    async def trigger_manual_rescan(self, project_id: str) -> None:
        """Enqueue a single project for rescan at manual priority.

        Args:
            project_id: ULID of the project to rescan.
        """
        path = await asyncio.to_thread(_lookup_project_path, project_id)
        if path is None:
            _log.warning(
                "Cannot rescan project %s: not found or no path",
                project_id,
            )
            return

        job = ScanJob(
            priority=PRIORITY_MANUAL,
            sequence=self._next_seq(),
            project_id=project_id,
            project_path=path,
        )
        await self._queue.put(job)
        _log.debug("Enqueued manual rescan for %s", project_id)

    async def trigger_incremental_scan(self, project_id: str) -> None:
        """Enqueue a single project for rescan at watcher priority.

        Args:
            project_id: ULID of the project to rescan.
        """
        path = await asyncio.to_thread(_lookup_project_path, project_id)
        if path is None:
            _log.warning(
                "Cannot incrementally scan project %s: not found or no path",
                project_id,
            )
            return

        job = ScanJob(
            priority=PRIORITY_WATCHER,
            sequence=self._next_seq(),
            project_id=project_id,
            project_path=path,
        )
        await self._queue.put(job)
        _log.debug("Enqueued incremental scan for %s", project_id)

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    async def _worker(self, worker_id: int) -> None:
        """Background task that consumes jobs from the priority queue.

        Runs in an infinite loop until a sentinel job is received.
        Each job is processed under the shared semaphore to limit
        concurrent analyzer invocations.

        Args:
            worker_id: Numeric identifier for logging purposes.
        """
        _log.debug("Worker %d started", worker_id)
        while True:
            job = await self._queue.get()
            try:
                if job.is_sentinel:
                    _log.debug("Worker %d received sentinel, exiting", worker_id)
                    break
                async with self._semaphore:
                    await self._analyze_project(
                        job.project_id, job.project_path
                    )
            except Exception:
                _log.exception(
                    "Worker %d failed processing %s",
                    worker_id,
                    job.project_id,
                )
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------------
    # Analyzer pipeline
    # ------------------------------------------------------------------

    async def _analyze_project(
        self, project_id: str, project_path: str
    ) -> None:
        """Run all analyzers for a single project and persist results.

        Acquires the per-project lock to prevent double-writes, runs
        the six analyzers (with independent ones in parallel), and
        persists the results to the database.

        Args:
            project_id: ULID of the project.
            project_path: Absolute filesystem path to the project
                directory.
        """
        lock = self._get_project_lock(project_id)
        async with lock:
            project_dir = Path(project_path)
            if not project_dir.is_dir():
                _log.warning("Project dir missing: %s", project_path)
                return
            analyzer_results = await self._run_analyzers(project_dir)
            changed_fields = await asyncio.to_thread(
                self._persist_results, project_id, analyzer_results
            )
            if changed_fields:
                await self._broadcast(
                    "project_updated",
                    {"id": project_id, "fields": changed_fields},
                )

    async def _run_analyzers(
        self, project_dir: Path
    ) -> dict[str, Any]:
        """Run all six analyzers for a project directory.

        The ``project_type`` and ``frameworks`` analyzers run
        sequentially (frameworks depends on the project type result).
        The remaining four analyzers (``languages``, ``git``,
        ``readme``, ``size``) run in parallel via ``asyncio.gather``.

        Each analyzer is wrapped in a try/except so that a failure in
        one does not prevent the others from running.

        Args:
            project_dir: Resolved absolute path to the project
                directory.

        Returns:
            A dict mapping analyzer names to their result dataclasses.
        """
        # Sequential: frameworks depends on project_type ---------------
        try:
            project_type = await asyncio.to_thread(
                detect_project_type, project_dir
            )
        except Exception:
            _log.exception(
                "project_type analyzer failed for %s", project_dir
            )
            project_type = _empty_project_type()

        try:
            frameworks = await asyncio.to_thread(
                detect_frameworks, project_dir, project_type
            )
        except Exception:
            _log.exception(
                "frameworks analyzer failed for %s", project_dir
            )
            frameworks = _empty_framework()

        # Parallel: these 4 are independent ----------------------------
        async def _safe_languages() -> LanguageBreakdownResult:
            try:
                return await asyncio.to_thread(
                    analyze_languages, project_dir
                )
            except Exception:
                _log.exception(
                    "languages analyzer failed for %s", project_dir
                )
                return _empty_languages()

        async def _safe_git() -> GitAnalysisResult:
            try:
                return await asyncio.to_thread(analyze_git, project_dir)
            except Exception:
                _log.exception(
                    "git analyzer failed for %s", project_dir
                )
                return _empty_git()

        async def _safe_readme() -> ReadmeResult:
            try:
                return await asyncio.to_thread(
                    extract_readme, project_dir, project_type.description
                )
            except Exception:
                _log.exception(
                    "readme analyzer failed for %s", project_dir
                )
                return _empty_readme()

        async def _safe_size() -> SizeResult:
            try:
                return await asyncio.to_thread(compute_size, project_dir)
            except Exception:
                _log.exception(
                    "size analyzer failed for %s", project_dir
                )
                return _empty_size()

        languages, git, readme, size = await asyncio.gather(
            _safe_languages(),
            _safe_git(),
            _safe_readme(),
            _safe_size(),
        )

        return {
            "project_type": project_type,
            "frameworks": frameworks,
            "languages": languages,
            "git": git,
            "readme": readme,
            "size": size,
        }

    def _persist_results(
        self, project_id: str, results: dict[str, Any]
    ) -> list[str]:
        """Map analyzer results onto the Project model and commit.

        Called via ``asyncio.to_thread`` so it runs in a thread pool
        executor with its own database session.

        Args:
            project_id: ULID of the project to update.
            results: Dict of analyzer name to result dataclass, as
                returned by ``_run_analyzers``.

        Returns:
            A list of field names that changed compared to the
            previously stored values.  Empty when nothing changed
            or the project was not found.
        """
        with Session(engine) as session:
            project = session.get(Project, project_id)
            if project is None:
                _log.warning(
                    "Project %s not found, skipping persist", project_id
                )
                return []

            # Snapshot for change detection --------------------------------
            before = {f: getattr(project, f) for f in _TRACKED_FIELDS}

            now = now_iso()

            pt: ProjectTypeResult = results["project_type"]
            fw: FrameworkDetectionResult = results["frameworks"]
            lang: LanguageBreakdownResult = results["languages"]
            git: GitAnalysisResult = results["git"]
            readme: ReadmeResult = results["readme"]
            size: SizeResult = results["size"]

            # Project type -------------------------------------------------
            project.package_manager = pt.package_manager

            # Frameworks (JSON array) --------------------------------------
            project.frameworks = json.dumps(fw.frameworks)

            # Languages (JSON object of percentages) -----------------------
            project.languages = json.dumps(lang.language_percentages)
            project.primary_language = lang.primary_language
            project.loc = lang.total_loc
            project.file_count = lang.file_count

            # Git ----------------------------------------------------------
            project.git_branch = git.branch
            project.git_dirty = git.dirty
            project.git_last_commit_hash = git.last_commit_hash
            project.git_last_commit_date = git.last_commit_date
            project.git_last_commit_msg = git.last_commit_msg
            project.git_branch_count = git.branch_count
            project.git_remote_url = git.remote_url

            # README -------------------------------------------------------
            if readme.snippet:
                project.description = readme.snippet

            # Size ---------------------------------------------------------
            project.size_bytes = size.size_bytes

            # Change detection ---------------------------------------------
            after = {f: getattr(project, f) for f in _TRACKED_FIELDS}
            changed = [f for f in _TRACKED_FIELDS if before[f] != after[f]]

            # Timestamps ---------------------------------------------------
            project.last_scanned_at = now
            project.updated_at = now

            session.add(project)
            session.commit()

            return changed
