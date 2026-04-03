"""Git metadata extraction for project directories.

Runs a series of ``git`` commands against a project directory and
returns structured metadata: current branch, dirty status, last commit
info (hash, date, subject), local branch count, and origin remote URL.

This module is pure: it performs subprocess I/O (shelling out to git)
but NO database I/O.  The caller (orchestrator) is responsible for
persisting results.

Design note: ARCHITECTURE.md §5.3 specifies ``asyncio.create_subprocess_exec``
for git commands.  This module uses synchronous ``subprocess.run`` instead,
consistent with all other analyzers (``size``, ``languages``, ``project_type``,
``frameworks``).  The orchestrator (Phase 14) will wrap calls in
``asyncio.to_thread()`` per ARCHITECTURE.md §9, which states blocking I/O
runs in a ThreadPoolExecutor.

Reference: ARCHITECTURE.md §5.3 — Phase 2d: Git Analysis.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GIT_TIMEOUT: int = 10
_PIPE_SEPARATOR: str = "|"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GitAnalysisResult:
    """Result of git metadata extraction for a project directory.

    Attributes:
        is_git_repo: Whether the directory is inside a git repository.
        branch: Current branch name, or None if detached HEAD or not
            a repo.
        dirty: True if there are uncommitted changes (working tree
            or index).
        last_commit_hash: Full SHA-1 hash of the most recent commit,
            or None.
        last_commit_date: ISO 8601 date of the most recent commit,
            or None.
        last_commit_msg: Subject line of the most recent commit, or
            None.
        branch_count: Number of local branches, or None if not a repo.
        remote_url: URL of the 'origin' remote, or None if no remote.
    """

    is_git_repo: bool
    branch: str | None
    dirty: bool
    last_commit_hash: str | None
    last_commit_date: str | None
    last_commit_msg: str | None
    branch_count: int | None
    remote_url: str | None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Path) -> str | None:
    """Run a git command and return stripped stdout, or None on failure.

    Args:
        args: Git subcommand and arguments (e.g.
            ``["rev-parse", "--abbrev-ref", "HEAD"]``).
        cwd: Working directory for the git command.

    Returns:
        Stripped stdout string on success (returncode 0), or None on
        any error (non-zero exit, timeout, missing git binary).
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

    if result.returncode != 0:
        return None

    return result.stdout.strip()


def _is_git_repo(project_dir: Path) -> bool:
    """Check whether *project_dir* is inside a git work tree.

    Uses ``git rev-parse --is-inside-work-tree`` which returns ``"true"``
    for directories inside a git repo and exits non-zero otherwise.

    Args:
        project_dir: Path to check.

    Returns:
        True if the path is inside a git work tree, False otherwise.
    """
    output = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=project_dir)
    return output == "true"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_git(project_dir: Path) -> GitAnalysisResult:
    """Extract git metadata from a project directory.

    Runs five git commands to gather branch, dirty status, last commit
    info, branch count, and remote URL.  Each command is independent
    and fails gracefully — a failure in one does not prevent the others
    from running.

    Non-git directories return an empty result with ``is_git_repo=False``
    and all fields set to ``None`` / ``False``.

    Args:
        project_dir: Path to the project directory.  Does not need
            to be pre-resolved — the function handles resolution.

    Returns:
        A ``GitAnalysisResult`` with extracted git metadata.
    """
    resolved = project_dir.resolve()

    if not _is_git_repo(resolved):
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

    # Branch -----------------------------------------------------------
    branch_output = _run_git(
        ["rev-parse", "--abbrev-ref", "HEAD"], cwd=resolved
    )
    branch = None if branch_output == "HEAD" else branch_output

    # Dirty ------------------------------------------------------------
    dirty_output = _run_git(["status", "--porcelain"], cwd=resolved)
    dirty = bool(dirty_output) if dirty_output is not None else False

    # Last commit ------------------------------------------------------
    last_commit_hash: str | None = None
    last_commit_date: str | None = None
    last_commit_msg: str | None = None

    log_format = _PIPE_SEPARATOR.join(["%H", "%aI", "%s"])
    log_output = _run_git(["log", "-1", f"--format={log_format}"], cwd=resolved)
    if log_output:
        parts = log_output.split(_PIPE_SEPARATOR, maxsplit=2)
        if len(parts) == 3:
            last_commit_hash = parts[0]
            last_commit_date = parts[1]
            last_commit_msg = parts[2]

    # Branch count -----------------------------------------------------
    branch_count: int | None = None
    branch_list_output = _run_git(["branch", "--list"], cwd=resolved)
    if branch_list_output is not None:
        lines = [line.strip() for line in branch_list_output.splitlines()]
        branch_count = len([line for line in lines if line])

    # Remote URL -------------------------------------------------------
    remote_url = _run_git(["remote", "get-url", "origin"], cwd=resolved)

    return GitAnalysisResult(
        is_git_repo=True,
        branch=branch,
        dirty=dirty,
        last_commit_hash=last_commit_hash,
        last_commit_date=last_commit_date,
        last_commit_msg=last_commit_msg,
        branch_count=branch_count,
        remote_url=remote_url,
    )
