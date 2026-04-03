"""Tests for the discovery module of the Engram scanning pipeline.

Validates directory enumeration, path resolution, hidden-directory
filtering, and the three-way diff (new / missing / existing) that
compares directories on disk against known database projects.

All tests use ``pytest``'s ``tmp_path`` fixture — no real project
directories are ever referenced.
"""

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# sys.path setup — mirrors conftest.py convention
# ---------------------------------------------------------------------------
_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from scanner.discovery import (  # noqa: E402
    DiscoveredDirectory,
    DiscoveryResult,
    KnownProject,
    discover,
    enumerate_directories,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_known(tmp_path: Path, name: str, *, id_: str = "01TEST") -> KnownProject:
    """Build a ``KnownProject`` whose path is under *tmp_path*."""
    return KnownProject(id=id_, name=name, path=str(tmp_path / name))


# ---------------------------------------------------------------------------
# TestEnumerateDirectories
# ---------------------------------------------------------------------------


class TestEnumerateDirectories:
    """Tests for ``enumerate_directories``."""

    def test_lists_immediate_child_directories(self, tmp_path: Path) -> None:
        """All non-hidden child directories are returned with resolved paths."""
        names = ["proj-a", "proj-b", "proj-c"]
        for n in names:
            (tmp_path / n).mkdir()

        result = enumerate_directories(tmp_path)

        assert len(result) == 3
        returned_names = {dd.name for dd in result.values()}
        assert returned_names == set(names)

        # Every value must have a resolved absolute path that matches the key.
        for abs_path, dd in result.items():
            assert abs_path == dd.path
            assert Path(abs_path).is_absolute()
            assert Path(abs_path).exists()

    def test_excludes_hidden_directories(self, tmp_path: Path) -> None:
        """Directories whose name starts with a dot are excluded."""
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".git").mkdir()
        (tmp_path / "visible").mkdir()

        result = enumerate_directories(tmp_path)

        assert len(result) == 1
        only_entry = next(iter(result.values()))
        assert only_entry.name == "visible"

    def test_excludes_files(self, tmp_path: Path) -> None:
        """Regular files are excluded — only directories are returned."""
        (tmp_path / "README.md").write_text("hello")
        (tmp_path / "project").mkdir()

        result = enumerate_directories(tmp_path)

        assert len(result) == 1
        assert next(iter(result.values())).name == "project"

    def test_empty_directory(self, tmp_path: Path) -> None:
        """An empty root directory returns an empty dict."""
        result = enumerate_directories(tmp_path)

        assert result == {}

    def test_nonexistent_directory_raises(self, tmp_path: Path) -> None:
        """A nonexistent path raises ``FileNotFoundError``."""
        bogus = tmp_path / "nonexistent" / "path"
        with pytest.raises(FileNotFoundError):
            enumerate_directories(bogus)

    def test_file_instead_of_directory_raises(self, tmp_path: Path) -> None:
        """A path that points to a file raises ``NotADirectoryError``."""
        file_path = tmp_path / "somefile.txt"
        file_path.write_text("not a directory")

        with pytest.raises(NotADirectoryError):
            enumerate_directories(file_path)

    def test_keys_are_resolved_absolute_paths(self, tmp_path: Path) -> None:
        """Dict keys are resolved absolute path strings."""
        (tmp_path / "alpha").mkdir()

        result = enumerate_directories(tmp_path)

        key = next(iter(result.keys()))
        assert key == str((tmp_path / "alpha").resolve())

    def test_mixed_files_and_dirs(self, tmp_path: Path) -> None:
        """Only directories are returned when the root contains both."""
        (tmp_path / "dir-one").mkdir()
        (tmp_path / "dir-two").mkdir()
        (tmp_path / "notes.txt").write_text("text")
        (tmp_path / ".secret").mkdir()

        result = enumerate_directories(tmp_path)

        names = {dd.name for dd in result.values()}
        assert names == {"dir-one", "dir-two"}

    def test_symlink_to_directory_is_included(self, tmp_path: Path) -> None:
        """A symlink pointing to a real directory is enumerated.

        ``pathlib.Path.is_dir()`` follows symlinks, so a symlink whose
        target is a directory passes the filter.  Because
        ``enumerate_directories`` keys results by *resolved* path, a
        symlink whose target lives outside the scanned root gets its
        own entry (whereas a sibling symlink to a co-located directory
        would collide on the same resolved key).
        """
        # Place the real directory outside the scanned root so the
        # symlink resolves to a unique path.
        external = tmp_path / "external"
        external.mkdir()
        real_target = external / "target-project"
        real_target.mkdir()

        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        (projects_root / "normal-project").mkdir()
        link = projects_root / "link-project"
        link.symlink_to(real_target)

        result = enumerate_directories(projects_root)

        names = {dd.name for dd in result.values()}
        assert "normal-project" in names
        assert "link-project" in names
        assert len(result) == 2

    def test_broken_symlink_is_excluded(self, tmp_path: Path) -> None:
        """A symlink whose target does not exist is excluded.

        ``pathlib.Path.is_dir()`` returns ``False`` for broken symlinks
        because the target cannot be stat'd, so they are correctly
        filtered out.
        """
        (tmp_path / "normal-dir").mkdir()
        broken_link = tmp_path / "dangling"
        broken_link.symlink_to(tmp_path / "nonexistent-target")

        result = enumerate_directories(tmp_path)

        assert len(result) == 1
        assert next(iter(result.values())).name == "normal-dir"


# ---------------------------------------------------------------------------
# TestDiscover
# ---------------------------------------------------------------------------


class TestDiscover:
    """Tests for ``discover``."""

    def test_all_new_directories(self, tmp_path: Path) -> None:
        """Directories on disk with no known projects are all classified as new."""
        for n in ["proj-a", "proj-b", "proj-c"]:
            (tmp_path / n).mkdir()

        result = discover(tmp_path, known_projects=[])

        assert len(result.new) == 3
        assert result.missing == []
        assert result.existing == []
        new_names = [d.name for d in result.new]
        assert set(new_names) == {"proj-a", "proj-b", "proj-c"}

    def test_all_missing_projects(self, tmp_path: Path) -> None:
        """Known projects whose directories no longer exist are classified as missing."""
        known = [
            KnownProject(id="01AAA", name="gone-a", path=str(tmp_path / "gone-a")),
            KnownProject(id="01BBB", name="gone-b", path=str(tmp_path / "gone-b")),
        ]

        result = discover(tmp_path, known_projects=known)

        assert result.new == []
        assert len(result.missing) == 2
        assert result.existing == []
        missing_names = {kp.name for kp in result.missing}
        assert missing_names == {"gone-a", "gone-b"}

    def test_all_existing(self, tmp_path: Path) -> None:
        """Known projects that still exist on disk are classified as existing."""
        (tmp_path / "proj-a").mkdir()
        (tmp_path / "proj-b").mkdir()

        known = [
            KnownProject(id="01AAA", name="proj-a", path=str(tmp_path / "proj-a")),
            KnownProject(id="01BBB", name="proj-b", path=str(tmp_path / "proj-b")),
        ]

        result = discover(tmp_path, known_projects=known)

        assert result.new == []
        assert result.missing == []
        assert len(result.existing) == 2
        existing_names = {kp.name for kp in result.existing}
        assert existing_names == {"proj-a", "proj-b"}

    def test_mixed_new_missing_existing(self, tmp_path: Path) -> None:
        """A mixed scenario correctly categorizes new, missing, and existing."""
        # On disk: proj-a, proj-b, proj-c
        for n in ["proj-a", "proj-b", "proj-c"]:
            (tmp_path / n).mkdir()

        # Known: proj-a (exists on disk) and proj-d (missing from disk)
        known = [
            KnownProject(id="01AAA", name="proj-a", path=str(tmp_path / "proj-a")),
            KnownProject(id="01DDD", name="proj-d", path=str(tmp_path / "proj-d")),
        ]

        result = discover(tmp_path, known_projects=known)

        new_names = {d.name for d in result.new}
        missing_names = {kp.name for kp in result.missing}
        existing_names = {kp.name for kp in result.existing}

        assert new_names == {"proj-b", "proj-c"}
        assert missing_names == {"proj-d"}
        assert existing_names == {"proj-a"}

    def test_hidden_directories_excluded_from_diff(self, tmp_path: Path) -> None:
        """Hidden directories on disk are never classified as new."""
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "visible").mkdir()

        result = discover(tmp_path, known_projects=[])

        assert len(result.new) == 1
        assert result.new[0].name == "visible"

    def test_projects_root_accepts_string(self, tmp_path: Path) -> None:
        """``discover`` accepts a plain string for *projects_root*."""
        (tmp_path / "alpha").mkdir()

        result = discover(str(tmp_path), known_projects=[])

        assert len(result.new) == 1
        assert result.new[0].name == "alpha"

    def test_result_projects_root_is_resolved(self, tmp_path: Path) -> None:
        """``result.projects_root`` is a resolved absolute path string."""
        result = discover(tmp_path, known_projects=[])

        assert result.projects_root == str(tmp_path.resolve())
        assert "~" not in result.projects_root
        assert Path(result.projects_root).is_absolute()

    def test_empty_known_projects_list(self, tmp_path: Path) -> None:
        """An empty ``known_projects`` list classifies all dirs as new."""
        (tmp_path / "one").mkdir()
        (tmp_path / "two").mkdir()

        result = discover(tmp_path, known_projects=[])

        assert len(result.new) == 2
        assert result.missing == []
        assert result.existing == []

    def test_sorted_output_new(self, tmp_path: Path) -> None:
        """New directories are sorted alphabetically by name (case-insensitive)."""
        for n in ["zebra", "apple", "mango"]:
            (tmp_path / n).mkdir()

        result = discover(tmp_path, known_projects=[])

        new_names = [d.name for d in result.new]
        assert new_names == ["apple", "mango", "zebra"]

    def test_sorted_output_missing(self, tmp_path: Path) -> None:
        """Missing projects are sorted alphabetically by name (case-insensitive)."""
        known = [
            KnownProject(id="01ZZZ", name="zebra", path=str(tmp_path / "zebra")),
            KnownProject(id="01AAA", name="apple", path=str(tmp_path / "apple")),
            KnownProject(id="01MMM", name="mango", path=str(tmp_path / "mango")),
        ]

        result = discover(tmp_path, known_projects=known)

        missing_names = [kp.name for kp in result.missing]
        assert missing_names == ["apple", "mango", "zebra"]

    def test_sorted_output_existing(self, tmp_path: Path) -> None:
        """Existing projects are sorted alphabetically by name (case-insensitive)."""
        for n in ["zebra", "apple", "mango"]:
            (tmp_path / n).mkdir()

        known = [
            KnownProject(id="01ZZZ", name="zebra", path=str(tmp_path / "zebra")),
            KnownProject(id="01AAA", name="apple", path=str(tmp_path / "apple")),
            KnownProject(id="01MMM", name="mango", path=str(tmp_path / "mango")),
        ]

        result = discover(tmp_path, known_projects=known)

        existing_names = [kp.name for kp in result.existing]
        assert existing_names == ["apple", "mango", "zebra"]

    def test_sort_is_case_insensitive(self, tmp_path: Path) -> None:
        """Sorting treats uppercase and lowercase names equally."""
        for n in ["Zebra", "apple", "Mango"]:
            (tmp_path / n).mkdir()

        result = discover(tmp_path, known_projects=[])

        new_names = [d.name for d in result.new]
        assert new_names == ["apple", "Mango", "Zebra"]

    def test_discover_propagates_file_not_found(self, tmp_path: Path) -> None:
        """``discover`` raises ``FileNotFoundError`` for a nonexistent root."""
        bogus = tmp_path / "does_not_exist"

        with pytest.raises(FileNotFoundError):
            discover(bogus, known_projects=[])

    def test_discover_propagates_not_a_directory(self, tmp_path: Path) -> None:
        """``discover`` raises ``NotADirectoryError`` when root is a file."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("nope")

        with pytest.raises(NotADirectoryError):
            discover(file_path, known_projects=[])

    def test_known_project_paths_are_resolved(self, tmp_path: Path) -> None:
        """Known project paths with extra components are resolved before comparison."""
        (tmp_path / "proj").mkdir()

        # Provide a known project path that uses a redundant parent traversal.
        # e.g., /tmp/.../proj/../proj which should resolve to /tmp/.../proj
        tricky_path = str(tmp_path / "proj" / ".." / "proj")
        known = [KnownProject(id="01AAA", name="proj", path=tricky_path)]

        result = discover(tmp_path, known_projects=known)

        assert result.new == []
        assert result.missing == []
        assert len(result.existing) == 1
        assert result.existing[0].name == "proj"

    def test_disjoint_categories(self, tmp_path: Path) -> None:
        """No project or directory appears in more than one category."""
        for n in ["shared", "disk-only"]:
            (tmp_path / n).mkdir()

        known = [
            KnownProject(id="01SSS", name="shared", path=str(tmp_path / "shared")),
            KnownProject(id="01GGG", name="gone", path=str(tmp_path / "gone")),
        ]

        result = discover(tmp_path, known_projects=known)

        new_paths = {d.path for d in result.new}
        missing_paths = {kp.path for kp in result.missing}
        existing_ids = {kp.id for kp in result.existing}

        # No overlap between new paths and existing/missing paths.
        assert new_paths.isdisjoint(missing_paths)
        assert len(result.new) == 1
        assert len(result.missing) == 1
        assert len(result.existing) == 1

        # Verify the correct classification.
        assert result.new[0].name == "disk-only"
        assert result.missing[0].name == "gone"
        assert result.existing[0].name == "shared"


# ---------------------------------------------------------------------------
# TestDataStructures
# ---------------------------------------------------------------------------


class TestDataStructures:
    """Tests for the frozen dataclass structures."""

    def test_discovered_directory_is_frozen(self) -> None:
        """``DiscoveredDirectory`` instances are immutable."""
        dd = DiscoveredDirectory(name="x", path="/x")
        with pytest.raises(AttributeError):
            dd.name = "y"  # type: ignore[misc]

    def test_known_project_is_frozen(self) -> None:
        """``KnownProject`` instances are immutable."""
        kp = KnownProject(id="01A", name="x", path="/x")
        with pytest.raises(AttributeError):
            kp.name = "y"  # type: ignore[misc]

    def test_discovery_result_is_frozen(self) -> None:
        """``DiscoveryResult`` instances are immutable."""
        dr = DiscoveryResult(new=[], missing=[], existing=[], projects_root="/r")
        with pytest.raises(AttributeError):
            dr.projects_root = "/other"  # type: ignore[misc]
