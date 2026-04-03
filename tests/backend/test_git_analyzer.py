"""Tests for the git metadata extraction module of the Engram scanning pipeline.

Validates git repository detection, branch info, dirty/clean status,
commit metadata parsing, multi-branch counting, detached HEAD handling,
remote URL extraction, commit message edge cases, and the frozen
dataclass contract.

All tests use ``pytest``'s ``tmp_path`` fixture with real temporary git
repositories -- no mocking and no references to real project directories.
"""

import re
import subprocess
import sys
from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# sys.path setup -- mirrors conftest.py convention
# ---------------------------------------------------------------------------
_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from scanner.analyzers.git_analyzer import GitAnalysisResult, analyze_git  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a git command in the given directory.

    Args:
        args: Git subcommand and arguments (e.g. ``["init"]``).
        cwd: Working directory for the git command.

    Returns:
        The completed process result.

    Raises:
        subprocess.CalledProcessError: If the git command exits non-zero.
    """
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    """Initialize a git repo with deterministic settings, return repo path.

    Creates a subdirectory ``repo`` inside *tmp_path*, initializes a git
    repository with the default branch set to ``main``, and configures
    a local user name and email for commits.

    Args:
        tmp_path: The pytest temporary directory.

    Returns:
        The path to the initialized repository.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["-c", "init.defaultBranch=main", "init"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    _git(["config", "user.email", "test@test.com"], cwd=repo)
    return repo


def _init_repo_with_commit(tmp_path: Path, msg: str = "initial commit") -> Path:
    """Initialize a repo, create a file, and make one commit.

    Args:
        tmp_path: The pytest temporary directory.
        msg: Commit message for the initial commit.

    Returns:
        The path to the repository with one commit.
    """
    repo = _init_repo(tmp_path)
    _make_file(repo / "file.txt", "hello")
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", msg], cwd=repo)
    return repo


def _make_file(path: Path, content: str = "") -> None:
    """Write a file, creating parent dirs if needed.

    Args:
        path: Absolute path to the file to create.
        content: Text content to write (defaults to empty string).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# TestNonGitDirectory
# ---------------------------------------------------------------------------


class TestNonGitDirectory:
    """Tests for directories that are NOT git repositories."""

    def test_non_git_directory(self, tmp_path: Path) -> None:
        """A plain directory yields is_git_repo=False with all fields None/False."""
        result = analyze_git(tmp_path)

        assert result.is_git_repo is False
        assert result.branch is None
        assert result.dirty is False
        assert result.last_commit_hash is None
        assert result.last_commit_date is None
        assert result.last_commit_msg is None
        assert result.branch_count is None
        assert result.remote_url is None

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        """A path that does not exist yields the same null result."""
        nonexistent = tmp_path / "does_not_exist"

        result = analyze_git(nonexistent)

        assert result.is_git_repo is False
        assert result.branch is None
        assert result.dirty is False
        assert result.last_commit_hash is None
        assert result.last_commit_date is None
        assert result.last_commit_msg is None
        assert result.branch_count is None
        assert result.remote_url is None

    def test_file_path(self, tmp_path: Path) -> None:
        """A file path (not a directory) yields the null result."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("some content")

        result = analyze_git(file_path)

        assert result.is_git_repo is False
        assert result.branch is None
        assert result.dirty is False
        assert result.last_commit_hash is None
        assert result.last_commit_date is None
        assert result.last_commit_msg is None
        assert result.branch_count is None
        assert result.remote_url is None


# ---------------------------------------------------------------------------
# TestBasicGitInfo
# ---------------------------------------------------------------------------


class TestBasicGitInfo:
    """Tests for basic git metadata from a repo with one commit."""

    def test_is_git_repo(self, tmp_path: Path) -> None:
        """A directory with a git repo yields is_git_repo=True."""
        repo = _init_repo_with_commit(tmp_path)

        result = analyze_git(repo)

        assert result.is_git_repo is True

    def test_current_branch(self, tmp_path: Path) -> None:
        """Default branch is 'main' when initialized with init.defaultBranch=main."""
        repo = _init_repo_with_commit(tmp_path)

        result = analyze_git(repo)

        assert result.branch == "main"

    def test_last_commit_hash(self, tmp_path: Path) -> None:
        """Last commit hash is a 40-character lowercase hex string."""
        repo = _init_repo_with_commit(tmp_path)

        result = analyze_git(repo)

        assert result.last_commit_hash is not None
        assert re.fullmatch(r"[0-9a-f]{40}", result.last_commit_hash)

    def test_last_commit_date(self, tmp_path: Path) -> None:
        """Last commit date is a valid ISO 8601 timestamp."""
        repo = _init_repo_with_commit(tmp_path)

        result = analyze_git(repo)

        assert result.last_commit_date is not None
        # datetime.fromisoformat can parse the git author date format
        parsed = datetime.fromisoformat(result.last_commit_date)
        assert isinstance(parsed, datetime)

    def test_last_commit_msg(self, tmp_path: Path) -> None:
        """Last commit message matches the message used during setup."""
        msg = "initial commit"
        repo = _init_repo_with_commit(tmp_path, msg=msg)

        result = analyze_git(repo)

        assert result.last_commit_msg == msg

    def test_branch_count_single(self, tmp_path: Path) -> None:
        """A repo with only the default branch has branch_count=1."""
        repo = _init_repo_with_commit(tmp_path)

        result = analyze_git(repo)

        assert result.branch_count == 1

    def test_no_remote(self, tmp_path: Path) -> None:
        """A freshly initialized repo has no origin remote."""
        repo = _init_repo_with_commit(tmp_path)

        result = analyze_git(repo)

        assert result.remote_url is None


# ---------------------------------------------------------------------------
# TestDirtyDetection
# ---------------------------------------------------------------------------


class TestDirtyDetection:
    """Tests for working tree dirty/clean status detection."""

    def test_clean_repo(self, tmp_path: Path) -> None:
        """A repo with all changes committed is not dirty."""
        repo = _init_repo_with_commit(tmp_path)

        result = analyze_git(repo)

        assert result.dirty is False

    def test_dirty_modified_file(self, tmp_path: Path) -> None:
        """Modifying a tracked file without committing marks dirty=True."""
        repo = _init_repo_with_commit(tmp_path)
        (repo / "file.txt").write_text("modified content", encoding="utf-8")

        result = analyze_git(repo)

        assert result.dirty is True

    def test_dirty_untracked_file(self, tmp_path: Path) -> None:
        """Adding an untracked file marks dirty=True."""
        repo = _init_repo_with_commit(tmp_path)
        _make_file(repo / "new_file.txt", "new content")

        result = analyze_git(repo)

        assert result.dirty is True

    def test_dirty_staged_changes(self, tmp_path: Path) -> None:
        """Staging changes without committing marks dirty=True."""
        repo = _init_repo_with_commit(tmp_path)
        _make_file(repo / "staged.txt", "staged content")
        _git(["add", "staged.txt"], cwd=repo)

        result = analyze_git(repo)

        assert result.dirty is True


# ---------------------------------------------------------------------------
# TestEmptyRepo
# ---------------------------------------------------------------------------


class TestEmptyRepo:
    """Tests for a git repo that has been initialized but has no commits."""

    def test_empty_repo_is_git(self, tmp_path: Path) -> None:
        """An initialized repo with no commits is still a git repo."""
        repo = _init_repo(tmp_path)

        result = analyze_git(repo)

        assert result.is_git_repo is True

    def test_empty_repo_no_commits(self, tmp_path: Path) -> None:
        """An empty repo has no commit hash, date, or message."""
        repo = _init_repo(tmp_path)

        result = analyze_git(repo)

        assert result.last_commit_hash is None
        assert result.last_commit_date is None
        assert result.last_commit_msg is None

    def test_empty_repo_branch_count(self, tmp_path: Path) -> None:
        """An empty repo (no commits) has branch_count=0."""
        repo = _init_repo(tmp_path)

        result = analyze_git(repo)

        assert result.branch_count == 0


# ---------------------------------------------------------------------------
# TestMultipleBranches
# ---------------------------------------------------------------------------


class TestMultipleBranches:
    """Tests for repositories with multiple local branches."""

    def test_branch_count_multiple(self, tmp_path: Path) -> None:
        """Creating 2 additional branches yields branch_count=3."""
        repo = _init_repo_with_commit(tmp_path)
        _git(["branch", "feature-a"], cwd=repo)
        _git(["branch", "feature-b"], cwd=repo)

        result = analyze_git(repo)

        assert result.branch_count == 3

    def test_branch_after_checkout(self, tmp_path: Path) -> None:
        """Switching to another branch reflects the new branch name."""
        repo = _init_repo_with_commit(tmp_path)
        _git(["branch", "develop"], cwd=repo)
        _git(["checkout", "develop"], cwd=repo)

        result = analyze_git(repo)

        assert result.branch == "develop"


# ---------------------------------------------------------------------------
# TestDetachedHead
# ---------------------------------------------------------------------------


class TestDetachedHead:
    """Tests for detached HEAD state."""

    def test_detached_head(self, tmp_path: Path) -> None:
        """Checking out a specific commit hash yields branch=None."""
        repo = _init_repo_with_commit(tmp_path)
        # Get the current commit hash
        cp = _git(["rev-parse", "HEAD"], cwd=repo)
        commit_hash = cp.stdout.strip()
        # Detach HEAD by checking out the commit directly
        _git(["checkout", commit_hash], cwd=repo)

        result = analyze_git(repo)

        assert result.is_git_repo is True
        assert result.branch is None


# ---------------------------------------------------------------------------
# TestRemoteUrl
# ---------------------------------------------------------------------------


class TestRemoteUrl:
    """Tests for remote URL extraction."""

    def test_remote_url(self, tmp_path: Path) -> None:
        """An 'origin' remote URL is correctly extracted."""
        repo = _init_repo_with_commit(tmp_path)
        expected_url = "https://github.com/user/repo.git"
        _git(["remote", "add", "origin", expected_url], cwd=repo)

        result = analyze_git(repo)

        assert result.remote_url == expected_url

    def test_non_origin_remote(self, tmp_path: Path) -> None:
        """A remote named 'upstream' (not 'origin') yields remote_url=None."""
        repo = _init_repo_with_commit(tmp_path)
        _git(
            ["remote", "add", "upstream", "https://github.com/other/repo.git"],
            cwd=repo,
        )

        result = analyze_git(repo)

        assert result.remote_url is None


# ---------------------------------------------------------------------------
# TestCommitMessageParsing
# ---------------------------------------------------------------------------


class TestCommitMessageParsing:
    """Tests for edge cases in commit message extraction."""

    def test_message_with_pipes(self, tmp_path: Path) -> None:
        """Commit messages containing pipe characters are preserved correctly.

        The analyzer uses ``|`` as the separator in ``--format``, but
        splits with ``maxsplit=2`` so pipes in the subject line survive.
        """
        msg = "feat: support A | B | C pipelines"
        repo = _init_repo_with_commit(tmp_path, msg=msg)

        result = analyze_git(repo)

        assert result.last_commit_msg == msg


# ---------------------------------------------------------------------------
# TestDataStructures
# ---------------------------------------------------------------------------


class TestDataStructures:
    """Tests for the frozen dataclass contract."""

    def test_frozen_result(self) -> None:
        """Assigning to GitAnalysisResult fields raises FrozenInstanceError."""
        result = GitAnalysisResult(
            is_git_repo=True,
            branch="main",
            dirty=False,
            last_commit_hash="a" * 40,
            last_commit_date="2025-01-01T00:00:00+00:00",
            last_commit_msg="initial commit",
            branch_count=1,
            remote_url=None,
        )

        with pytest.raises(FrozenInstanceError):
            result.branch = "other"  # type: ignore[misc]
