"""Discovery phase of the Engram scanning pipeline.

Enumerates immediate child directories under the configured
``projects_root`` and diffs them against known projects in the
database.  The result is a three-way split:

* **new** — directories on disk with no matching DB project.
* **missing** — DB projects whose directories no longer exist.
* **existing** — DB projects whose directories are still present.

This module is pure: it performs no database I/O and has no side
effects.  The caller (orchestrator) is responsible for fetching
known projects from the DB and acting on the discovery result.

Reference: ARCHITECTURE.md §5.2 — Phase 1: Discovery.
"""

from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveredDirectory:
    """A directory found on disk during discovery.

    Attributes:
        name: Directory basename (e.g. ``"myproject"``).
        path: Resolved absolute path (e.g.
            ``"/Users/foo/projects/myproject"``).
    """

    name: str
    path: str


@dataclass(frozen=True)
class KnownProject:
    """A project already tracked in the database.

    This is a lightweight projection — only the fields needed for the
    discovery diff.  The caller constructs these from full ORM rows.

    Attributes:
        id: ULID primary key.
        name: Project display name.
        path: Stored path from the database.
    """

    id: str
    name: str
    path: str


@dataclass(frozen=True)
class DiscoveryResult:
    """Categorized results of diffing disk directories against known projects.

    Attributes:
        new: Directories on disk that have no matching DB project.
        missing: DB projects whose directories are no longer on disk.
        existing: DB projects whose directories still exist on disk.
        projects_root: The resolved absolute root path that was scanned.
    """

    new: list[DiscoveredDirectory]
    missing: list[KnownProject]
    existing: list[KnownProject]
    projects_root: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enumerate_directories(
    projects_root: Path,
) -> dict[str, DiscoveredDirectory]:
    """List non-hidden child directories under *projects_root*.

    Args:
        projects_root: The root directory to scan.  Must be an existing
            directory.

    Returns:
        A dict keyed by resolved absolute path string mapping to the
        corresponding ``DiscoveredDirectory``.

    Raises:
        FileNotFoundError: If *projects_root* does not exist.
        NotADirectoryError: If *projects_root* exists but is not a
            directory.
    """
    resolved = projects_root.resolve()

    if not resolved.exists():
        raise FileNotFoundError(
            f"Projects root does not exist: {resolved}"
        )
    if not resolved.is_dir():
        raise NotADirectoryError(
            f"Projects root is not a directory: {resolved}"
        )

    result: dict[str, DiscoveredDirectory] = {}
    for child in resolved.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            abs_path = str(child.resolve())
            result[abs_path] = DiscoveredDirectory(
                name=child.name,
                path=abs_path,
            )
    return result


def discover(
    projects_root: str | Path,
    known_projects: list[KnownProject],
) -> DiscoveryResult:
    """Diff directories on disk against known database projects.

    Resolves all paths to absolute form before comparison so that
    relative paths, symlinks, and home-dir tildes are handled
    consistently.

    Args:
        projects_root: Path (string or ``Path``) to the directory
            containing all coding projects.  Supports ``~`` expansion.
        known_projects: Lightweight projections of projects already
            tracked in the database.

    Returns:
        A ``DiscoveryResult`` with three disjoint lists categorizing
        every directory and known project.

    Raises:
        FileNotFoundError: If *projects_root* does not exist.
        NotADirectoryError: If *projects_root* is not a directory.
    """
    resolved_root = Path(str(projects_root)).expanduser().resolve()

    # enumerate_directories validates existence and dir-ness
    dirs_on_disk = enumerate_directories(resolved_root)

    # Build lookup of known projects keyed by resolved absolute path.
    known_by_path: dict[str, KnownProject] = {}
    for kp in known_projects:
        resolved_kp_path = str(Path(kp.path).expanduser().resolve())
        known_by_path[resolved_kp_path] = kp

    disk_paths = dirs_on_disk.keys()
    known_paths = known_by_path.keys()

    new_paths = disk_paths - known_paths
    missing_paths = known_paths - disk_paths
    existing_paths = disk_paths & known_paths

    return DiscoveryResult(
        new=sorted(
            [dirs_on_disk[p] for p in new_paths],
            key=lambda d: d.name.lower(),
        ),
        missing=sorted(
            [known_by_path[p] for p in missing_paths],
            key=lambda kp: kp.name.lower(),
        ),
        existing=sorted(
            [known_by_path[p] for p in existing_paths],
            key=lambda kp: kp.name.lower(),
        ),
        projects_root=str(resolved_root),
    )
