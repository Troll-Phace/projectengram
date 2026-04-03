"""Tests for the size computation module of the Engram scanning pipeline.

Validates total size calculation, file counting (all files vs source-only),
directory exclusion during tree walks, edge cases (nonexistent paths, files
instead of dirs), and the frozen dataclass contract.

All tests use ``pytest``'s ``tmp_path`` fixture for filesystem tests --
no real project directories are ever referenced.
"""

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# sys.path setup -- mirrors conftest.py convention
# ---------------------------------------------------------------------------
_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from scanner.analyzers.size import SizeResult, compute_size  # noqa: E402
from scanner.analyzers._constants import SOURCE_EXTENSIONS  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(path: Path, content: str = "") -> None:
    """Write a file, creating parent dirs if needed.

    Args:
        path: Absolute path to the file to create.
        content: Text content to write (defaults to empty string).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_project(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a project directory with the given file structure.

    Args:
        tmp_path: The pytest temporary directory.
        files: Mapping of relative file paths to their text content.

    Returns:
        The project root directory (same as ``tmp_path``).
    """
    for rel_path, content in files.items():
        _make_file(tmp_path / rel_path, content)
    return tmp_path


# ---------------------------------------------------------------------------
# TestBasicSizeComputation
# ---------------------------------------------------------------------------


class TestBasicSizeComputation:
    """Tests for basic size and file counting behaviour."""

    def test_single_file(self, tmp_path: Path) -> None:
        """One file with known content 'hello\\n' yields size_bytes=6, file_count=1."""
        _make_file(tmp_path / "hello.txt", "hello\n")

        result = compute_size(tmp_path)

        assert result.size_bytes == 6
        assert result.file_count == 1

    def test_multiple_files(self, tmp_path: Path) -> None:
        """Three files with known content yield size_bytes equal to the sum of individual sizes."""
        contents = {"a.py": "abc", "b.txt": "defgh", "c.rs": "ij"}
        _make_project(tmp_path, contents)

        expected_size = sum(len(c.encode("utf-8")) for c in contents.values())
        result = compute_size(tmp_path)

        assert result.size_bytes == expected_size
        assert result.file_count == 3

    def test_empty_directory(self, tmp_path: Path) -> None:
        """An empty directory yields SizeResult(0, 0, 0)."""
        result = compute_size(tmp_path)

        assert result == SizeResult(0, 0, 0)

    def test_empty_files(self, tmp_path: Path) -> None:
        """Files with no content have size_bytes=0 but file_count > 0."""
        _make_project(tmp_path, {"empty1.py": "", "empty2.ts": "", "empty3.txt": ""})

        result = compute_size(tmp_path)

        assert result.size_bytes == 0
        assert result.file_count == 3


# ---------------------------------------------------------------------------
# TestFileCount
# ---------------------------------------------------------------------------


class TestFileCount:
    """Tests for file_count vs source_file_count classification."""

    def test_all_files_counted(self, tmp_path: Path) -> None:
        """A mix of .py, .ts, .png, .pdf files all contribute to file_count."""
        _make_project(
            tmp_path,
            {
                "main.py": "pass",
                "index.ts": "export {}",
                "logo.png": "PNG_DATA",
                "doc.pdf": "PDF_DATA",
            },
        )

        result = compute_size(tmp_path)

        assert result.file_count == 4

    def test_source_vs_nonsource(self, tmp_path: Path) -> None:
        """Source extensions (.py, .ts) are counted separately from non-source (.png, .pdf)."""
        _make_project(
            tmp_path,
            {
                "main.py": "pass",
                "index.ts": "export {}",
                "logo.png": "PNG_DATA",
                "doc.pdf": "PDF_DATA",
            },
        )

        result = compute_size(tmp_path)

        assert result.file_count == 4
        assert result.source_file_count == 2

    def test_config_files_are_source(self, tmp_path: Path) -> None:
        """.json and .yaml files are in SOURCE_EXTENSIONS and counted as source."""
        _make_project(
            tmp_path,
            {
                "config.json": "{}",
                "settings.yaml": "key: val",
                "data.csv": "a,b,c",
            },
        )

        result = compute_size(tmp_path)

        assert result.file_count == 3
        assert result.source_file_count == 2

    def test_no_extension_not_source(self, tmp_path: Path) -> None:
        """Files without extensions (Makefile, Dockerfile) are counted in file_count but not source_file_count."""
        _make_project(
            tmp_path,
            {
                "Makefile": "all: build",
                "Dockerfile": "FROM python:3.12",
                "LICENSE": "MIT",
            },
        )

        result = compute_size(tmp_path)

        assert result.file_count == 3
        assert result.source_file_count == 0


# ---------------------------------------------------------------------------
# TestExcludedDirectories
# ---------------------------------------------------------------------------


class TestExcludedDirectories:
    """Tests for directory pruning during tree walk."""

    def test_node_modules_excluded(self, tmp_path: Path) -> None:
        """Files inside node_modules/ are not counted in any metric."""
        _make_project(
            tmp_path,
            {
                "index.js": "console.log('hi')",
                "node_modules/lodash/lodash.js": "// lodash",
                "node_modules/express/index.js": "// express",
            },
        )

        result = compute_size(tmp_path)

        assert result.file_count == 1
        assert result.source_file_count == 1
        assert result.size_bytes == len("console.log('hi')".encode("utf-8"))

    def test_git_excluded(self, tmp_path: Path) -> None:
        """.git/ files are excluded from all metrics."""
        _make_project(
            tmp_path,
            {
                "main.py": "print('hello')",
                ".git/HEAD": "ref: refs/heads/main",
                ".git/config": "[core]\nrepositoryformatversion = 0",
            },
        )

        result = compute_size(tmp_path)

        assert result.file_count == 1
        assert result.source_file_count == 1

    def test_build_and_dist_excluded(self, tmp_path: Path) -> None:
        """build/ and dist/ directories are excluded."""
        _make_project(
            tmp_path,
            {
                "src/app.ts": "const x = 1;",
                "build/app.js": "var x = 1;",
                "dist/bundle.js": "var bundle = {};",
            },
        )

        result = compute_size(tmp_path)

        assert result.file_count == 1
        assert result.source_file_count == 1

    def test_multiple_excluded_dirs(self, tmp_path: Path) -> None:
        """Several excluded directories in one project are all pruned."""
        _make_project(
            tmp_path,
            {
                "app.py": "pass",
                "node_modules/pkg/index.js": "module.exports = {}",
                ".git/HEAD": "ref: refs/heads/main",
                "__pycache__/app.cpython-312.pyc": "bytecode",
                "venv/lib/site-packages/pkg.py": "# vendor",
                ".venv/bin/activate": "# activate",
                "target/debug/binary": "ELF",
                ".mypy_cache/data.json": "{}",
            },
        )

        result = compute_size(tmp_path)

        assert result.file_count == 1
        assert result.source_file_count == 1

    def test_normal_subdirs_included(self, tmp_path: Path) -> None:
        """Files in standard subdirectories (src/, lib/, app/) ARE counted."""
        _make_project(
            tmp_path,
            {
                "src/main.py": "pass",
                "lib/utils.py": "pass",
                "app/server.py": "pass",
                "tests/test_main.py": "pass",
            },
        )

        result = compute_size(tmp_path)

        assert result.file_count == 4
        assert result.source_file_count == 4

    def test_egg_info_excluded(self, tmp_path: Path) -> None:
        """Directories ending in .egg-info are excluded via is_excluded_dir."""
        _make_project(
            tmp_path,
            {
                "setup.py": "from setuptools import setup",
                "mypackage.egg-info/PKG-INFO": "Name: mypackage",
                "mypackage.egg-info/SOURCES.txt": "setup.py",
            },
        )

        result = compute_size(tmp_path)

        assert result.file_count == 1
        assert result.source_file_count == 1


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for boundary conditions and unusual inputs."""

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        """A path that does not exist returns SizeResult(0, 0, 0)."""
        nonexistent = tmp_path / "does_not_exist"

        result = compute_size(nonexistent)

        assert result == SizeResult(0, 0, 0)

    def test_file_instead_of_directory(self, tmp_path: Path) -> None:
        """A path that is a file (not a directory) returns SizeResult(0, 0, 0)."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("some content")

        result = compute_size(file_path)

        assert result == SizeResult(0, 0, 0)

    def test_nested_files(self, tmp_path: Path) -> None:
        """Files at various depths are all counted correctly."""
        _make_project(
            tmp_path,
            {
                "root.py": "r",
                "a/level1.py": "l1",
                "a/b/level2.py": "l2a",
                "a/b/c/level3.py": "l3",
                "x/y/z/deep.py": "deep",
            },
        )

        result = compute_size(tmp_path)

        assert result.file_count == 5
        assert result.source_file_count == 5
        expected_size = sum(
            len(c.encode("utf-8")) for c in ["r", "l1", "l2a", "l3", "deep"]
        )
        assert result.size_bytes == expected_size

    def test_many_files(self, tmp_path: Path) -> None:
        """Create 50+ files and verify counts match exactly."""
        num_files = 55
        files = {}
        for i in range(num_files):
            files[f"file_{i:03d}.py"] = f"# file {i}"
        _make_project(tmp_path, files)

        result = compute_size(tmp_path)

        assert result.file_count == num_files
        assert result.source_file_count == num_files
        expected_size = sum(len(c.encode("utf-8")) for c in files.values())
        assert result.size_bytes == expected_size


# ---------------------------------------------------------------------------
# TestDataStructures
# ---------------------------------------------------------------------------


class TestDataStructures:
    """Tests for the frozen dataclass and shared constants."""

    def test_result_is_frozen(self) -> None:
        """Assigning to SizeResult.size_bytes raises FrozenInstanceError."""
        result = SizeResult(size_bytes=100, file_count=5, source_file_count=3)

        with pytest.raises(FrozenInstanceError):
            result.size_bytes = 999  # type: ignore[misc]

    def test_source_extensions_contains_code_extensions(self) -> None:
        """Core code extensions (.py, .ts, .rs) are in SOURCE_EXTENSIONS."""
        for ext in (".py", ".ts", ".rs", ".go", ".js", ".tsx", ".jsx"):
            assert ext in SOURCE_EXTENSIONS, f"Expected '{ext}' in SOURCE_EXTENSIONS"

    def test_source_extensions_contains_config_extensions(self) -> None:
        """Config extensions (.json, .yaml, .yml, .toml) are in SOURCE_EXTENSIONS."""
        for ext in (".json", ".yaml", ".yml", ".toml", ".xml"):
            assert ext in SOURCE_EXTENSIONS, f"Expected '{ext}' in SOURCE_EXTENSIONS"


# ---------------------------------------------------------------------------
# TestSizeAccuracy
# ---------------------------------------------------------------------------


class TestSizeAccuracy:
    """Tests for byte-accurate size computation."""

    def test_size_matches_actual_bytes(self, tmp_path: Path) -> None:
        """Written content has a size_bytes equal to len(content.encode('utf-8'))."""
        content_a = "Hello, World!\n"
        content_b = "x = 42\ny = 'test'\n"
        _make_project(
            tmp_path,
            {"a.py": content_a, "b.py": content_b},
        )

        result = compute_size(tmp_path)

        expected = len(content_a.encode("utf-8")) + len(content_b.encode("utf-8"))
        assert result.size_bytes == expected

    def test_binary_file_size(self, tmp_path: Path) -> None:
        """Raw bytes written to a file are measured accurately by size_bytes."""
        raw_bytes = bytes(range(256))
        bin_path = tmp_path / "data.bin"
        bin_path.write_bytes(raw_bytes)

        result = compute_size(tmp_path)

        assert result.size_bytes == 256
        assert result.file_count == 1
        assert result.source_file_count == 0  # .bin is not a source extension

    def test_subdirectory_sizes_included(self, tmp_path: Path) -> None:
        """Files in nested subdirectories contribute to total size_bytes."""
        content_root = "root_data"
        content_sub = "sub_data_longer"
        content_deep = "deep_data"
        _make_project(
            tmp_path,
            {
                "root.txt": content_root,
                "sub/nested.txt": content_sub,
                "sub/deep/deeper.txt": content_deep,
            },
        )

        result = compute_size(tmp_path)

        expected = sum(
            len(c.encode("utf-8"))
            for c in [content_root, content_sub, content_deep]
        )
        assert result.size_bytes == expected
        assert result.file_count == 3

    def test_unicode_content_size(self, tmp_path: Path) -> None:
        """Multi-byte Unicode characters contribute correct byte counts."""
        # Each emoji is 4 bytes in UTF-8
        content = "cafe\u0301"  # 'e' + combining accent = 6 bytes
        _make_file(tmp_path / "unicode.py", content)

        result = compute_size(tmp_path)

        assert result.size_bytes == len(content.encode("utf-8"))

    def test_mixed_source_and_nonsource_sizes(self, tmp_path: Path) -> None:
        """Both source and non-source files contribute to total size_bytes."""
        _make_project(
            tmp_path,
            {
                "code.py": "import os",
                "image.png": "FAKE_PNG_HEADER_DATA",
                "config.json": '{"key": "value"}',
            },
        )

        result = compute_size(tmp_path)

        expected = sum(
            len(c.encode("utf-8"))
            for c in ["import os", "FAKE_PNG_HEADER_DATA", '{"key": "value"}']
        )
        assert result.size_bytes == expected
        assert result.file_count == 3
        # .py and .json are source; .png is not
        assert result.source_file_count == 2
