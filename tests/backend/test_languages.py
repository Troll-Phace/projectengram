"""Tests for the language analysis module of the Engram scanning pipeline.

Validates file extension to language mapping, line counting, directory
exclusion, percentage computation, primary language selection, and
edge cases such as binary files, empty directories, and non-existent paths.

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

from scanner.analyzers.languages import (  # noqa: E402
    LanguageBreakdownResult,
    analyze_languages,
)
from scanner.analyzers._constants import (  # noqa: E402
    CONFIG_EXTENSIONS,
    EXCLUDED_DIRS,
    EXTENSION_LANGUAGE_MAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(path: Path, content: str = "") -> None:
    """Write a file, creating parent dirs if needed.

    Args:
        path: Absolute path for the file to create.
        content: Text content to write into the file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_project(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a project directory with the given file structure.

    Args:
        tmp_path: The pytest ``tmp_path`` fixture root.
        files: Mapping of relative file paths to text content.

    Returns:
        The project directory path (same as ``tmp_path``).
    """
    for rel_path, content in files.items():
        _make_file(tmp_path / rel_path, content)
    return tmp_path


def _lines(n: int) -> str:
    """Generate a string with exactly *n* lines.

    Each line has the form ``line 1\\n``, ``line 2\\n``, etc.

    Args:
        n: Number of lines to generate.

    Returns:
        A string whose ``splitlines()`` length equals *n*.
    """
    return "".join(f"line {i + 1}\n" for i in range(n))


# ---------------------------------------------------------------------------
# TestBasicLanguageCounting
# ---------------------------------------------------------------------------


class TestBasicLanguageCounting:
    """Tests for fundamental language detection and line counting."""

    def test_single_python_file(self, tmp_path: Path) -> None:
        """One ``main.py`` with 10 lines produces LOC=10, primary=Python, 100%."""
        _make_project(tmp_path, {"main.py": _lines(10)})

        result = analyze_languages(tmp_path)

        assert result.primary_language == "Python"
        assert result.total_loc == 10
        assert result.file_count == 1
        assert result.language_percentages == {"Python": 1.0}
        assert result.lines_by_language == {"Python": 10}

    def test_single_typescript_file(self, tmp_path: Path) -> None:
        """One ``app.ts`` with 5 lines produces primary=TypeScript."""
        _make_project(tmp_path, {"app.ts": _lines(5)})

        result = analyze_languages(tmp_path)

        assert result.primary_language == "TypeScript"
        assert result.total_loc == 5
        assert result.file_count == 1

    def test_multiple_languages(self, tmp_path: Path) -> None:
        """Three languages counted correctly with proper primary and percentages."""
        _make_project(
            tmp_path,
            {
                "main.py": _lines(10),
                "app.ts": _lines(20),
                "lib.rs": _lines(5),
            },
        )

        result = analyze_languages(tmp_path)

        assert result.primary_language == "TypeScript"
        assert result.total_loc == 35
        assert result.file_count == 3
        assert result.lines_by_language == {
            "Python": 10,
            "TypeScript": 20,
            "Rust": 5,
        }
        # Percentages: TS=20/35, Py=10/35, Rust=5/35
        assert result.language_percentages["TypeScript"] == pytest.approx(
            round(20 / 35, 4)
        )
        assert result.language_percentages["Python"] == pytest.approx(
            round(10 / 35, 4)
        )
        assert result.language_percentages["Rust"] == pytest.approx(
            round(5 / 35, 4)
        )

    def test_empty_directory(self, tmp_path: Path) -> None:
        """An empty directory returns primary=None, total_loc=0, empty dicts."""
        result = analyze_languages(tmp_path)

        assert result.primary_language is None
        assert result.total_loc == 0
        assert result.file_count == 0
        assert result.language_percentages == {}

    def test_no_recognized_extensions(self, tmp_path: Path) -> None:
        """Files with unrecognised extensions produce an empty result."""
        _make_project(
            tmp_path,
            {
                "data.xyz": "some data\n",
                "config.abc": "key=val\n",
            },
        )

        result = analyze_languages(tmp_path)

        assert result.primary_language is None
        assert result.total_loc == 0
        assert result.file_count == 0


# ---------------------------------------------------------------------------
# TestExcludedDirectories
# ---------------------------------------------------------------------------


class TestExcludedDirectories:
    """Tests for directory exclusion during tree walks."""

    def test_node_modules_excluded(self, tmp_path: Path) -> None:
        """Files inside ``node_modules/`` are not counted; root files are."""
        _make_project(
            tmp_path,
            {
                "index.js": _lines(5),
                "node_modules/dep/index.js": _lines(100),
            },
        )

        result = analyze_languages(tmp_path)

        assert result.total_loc == 5
        assert result.file_count == 1

    def test_git_directory_excluded(self, tmp_path: Path) -> None:
        """Files inside ``.git/`` are not counted."""
        _make_project(
            tmp_path,
            {
                "main.py": _lines(3),
                ".git/objects/abc123": _lines(50),
                ".git/HEAD": "ref: refs/heads/main\n",
            },
        )

        result = analyze_languages(tmp_path)

        assert result.total_loc == 3
        assert result.file_count == 1

    def test_pycache_excluded(self, tmp_path: Path) -> None:
        """Python files inside ``__pycache__/`` are not counted."""
        _make_project(
            tmp_path,
            {
                "app.py": _lines(8),
                "__pycache__/app.cpython-312.py": _lines(20),
            },
        )

        result = analyze_languages(tmp_path)

        assert result.total_loc == 8
        assert result.file_count == 1

    def test_venv_excluded(self, tmp_path: Path) -> None:
        """Python files inside ``venv/`` are not counted."""
        _make_project(
            tmp_path,
            {
                "main.py": _lines(4),
                "venv/lib/python3.12/site-packages/pkg/module.py": _lines(200),
            },
        )

        result = analyze_languages(tmp_path)

        assert result.total_loc == 4
        assert result.file_count == 1

    def test_nested_excluded_dir(self, tmp_path: Path) -> None:
        """``src/node_modules/foo.js`` not counted but ``src/app.js`` is."""
        _make_project(
            tmp_path,
            {
                "src/app.js": _lines(10),
                "src/node_modules/foo.js": _lines(50),
            },
        )

        result = analyze_languages(tmp_path)

        assert result.total_loc == 10
        assert result.file_count == 1

    def test_normal_subdirs_included(self, tmp_path: Path) -> None:
        """Files in ``src/``, ``lib/``, ``app/`` are counted normally."""
        _make_project(
            tmp_path,
            {
                "src/main.py": _lines(5),
                "lib/utils.py": _lines(3),
                "app/server.py": _lines(7),
            },
        )

        result = analyze_languages(tmp_path)

        assert result.total_loc == 15
        assert result.file_count == 3

    def test_egg_info_excluded(self, tmp_path: Path) -> None:
        """Files in ``mypackage.egg-info/`` are not counted."""
        _make_project(
            tmp_path,
            {
                "main.py": _lines(6),
                "mypackage.egg-info/PKG-INFO.py": _lines(30),
            },
        )

        result = analyze_languages(tmp_path)

        assert result.total_loc == 6
        assert result.file_count == 1


# ---------------------------------------------------------------------------
# TestPrimaryLanguage
# ---------------------------------------------------------------------------


class TestPrimaryLanguage:
    """Tests for primary language selection."""

    def test_primary_is_highest_loc(self, tmp_path: Path) -> None:
        """The language with the most LOC is selected as primary."""
        _make_project(
            tmp_path,
            {
                "main.py": _lines(20),
                "app.ts": _lines(10),
            },
        )

        result = analyze_languages(tmp_path)

        assert result.primary_language == "Python"

    def test_primary_with_equal_loc_is_deterministic(self, tmp_path: Path) -> None:
        """When two languages have equal LOC, the result is deterministic.

        The ``max()`` function returns the first maximum found in iteration
        order.  The important thing is that the result does not change
        between runs -- the test verifies consistency across two calls.
        """
        _make_project(
            tmp_path,
            {
                "main.py": _lines(10),
                "lib.rs": _lines(10),
            },
        )

        result_a = analyze_languages(tmp_path)
        result_b = analyze_languages(tmp_path)

        assert result_a.primary_language is not None
        assert result_a.primary_language == result_b.primary_language
        assert result_a.primary_language in {"Python", "Rust"}


# ---------------------------------------------------------------------------
# TestPercentages
# ---------------------------------------------------------------------------


class TestPercentages:
    """Tests for percentage computation and ordering."""

    def test_percentages_sum_to_approximately_one(self, tmp_path: Path) -> None:
        """The sum of all language percentages is close to 1.0."""
        _make_project(
            tmp_path,
            {
                "main.py": _lines(7),
                "app.ts": _lines(13),
                "lib.rs": _lines(3),
            },
        )

        result = analyze_languages(tmp_path)

        total = sum(result.language_percentages.values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_percentages_sorted_descending(self, tmp_path: Path) -> None:
        """Dict keys appear in descending percentage order."""
        _make_project(
            tmp_path,
            {
                "main.py": _lines(5),
                "app.ts": _lines(20),
                "lib.rs": _lines(10),
                "style.css": _lines(3),
            },
        )

        result = analyze_languages(tmp_path)
        values = list(result.language_percentages.values())

        assert values == sorted(values, reverse=True)

    def test_single_language_is_100_percent(self, tmp_path: Path) -> None:
        """A single language yields exactly 1.0 (100%)."""
        _make_project(tmp_path, {"main.py": _lines(42)})

        result = analyze_languages(tmp_path)

        assert result.language_percentages == {"Python": 1.0}

    def test_percentages_rounded_to_four_decimals(self, tmp_path: Path) -> None:
        """No percentage has more than 4 decimal places."""
        _make_project(
            tmp_path,
            {
                "a.py": _lines(7),
                "b.ts": _lines(11),
                "c.rs": _lines(3),
            },
        )

        result = analyze_languages(tmp_path)

        for lang, pct in result.language_percentages.items():
            # Round to 4 decimals and verify the value is unchanged.
            assert pct == round(pct, 4), (
                f"{lang} percentage {pct} has more than 4 decimal places"
            )


# ---------------------------------------------------------------------------
# TestLineCountingEdgeCases
# ---------------------------------------------------------------------------


class TestLineCountingEdgeCases:
    """Tests for edge cases in line counting."""

    def test_empty_file(self, tmp_path: Path) -> None:
        """An empty recognised file contributes 0 lines but increments file_count."""
        _make_project(tmp_path, {"empty.py": ""})

        result = analyze_languages(tmp_path)

        assert result.file_count == 1
        assert result.total_loc == 0
        assert result.primary_language is None

    def test_file_with_only_newlines(self, tmp_path: Path) -> None:
        """A file containing only newline characters counts each newline as a line."""
        _make_project(tmp_path, {"blank.py": "\n\n\n"})

        result = analyze_languages(tmp_path)

        assert result.lines_by_language["Python"] == 3
        assert result.total_loc == 3

    def test_unicode_content(self, tmp_path: Path) -> None:
        """Files with CJK characters and emoji are counted correctly."""
        content = "# Chinese: \u4f60\u597d\u4e16\u754c\n# Emoji: \U0001f680\U0001f30d\n# Normal line\n"
        _make_project(tmp_path, {"unicode.py": content})

        result = analyze_languages(tmp_path)

        assert result.lines_by_language["Python"] == 3
        assert result.total_loc == 3

    def test_binary_content_graceful(self, tmp_path: Path) -> None:
        """A file with invalid UTF-8 bytes does not crash the analyzer.

        The ``_count_lines`` helper falls back to latin-1, so the file
        may still be counted.  The key requirement is no exception.
        """
        binary_path = tmp_path / "binary.py"
        binary_path.parent.mkdir(parents=True, exist_ok=True)
        binary_path.write_bytes(b"\x80\x81\x82\xff\xfe\n\x00\x01\n")

        result = analyze_languages(tmp_path)

        # Must not raise; file_count should still be 1 (it is a .py file).
        assert result.file_count == 1
        # Line count might be 0 or a fallback-counted number -- we only
        # assert it does not crash and returns a non-negative value.
        assert result.total_loc >= 0


# ---------------------------------------------------------------------------
# TestNonExistentPath
# ---------------------------------------------------------------------------


class TestNonExistentPath:
    """Tests for paths that do not exist or are not directories."""

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        """A path that does not exist returns an empty result."""
        missing = tmp_path / "no_such_directory"

        result = analyze_languages(missing)

        assert result.primary_language is None
        assert result.total_loc == 0
        assert result.file_count == 0
        assert result.language_percentages == {}
        assert result.lines_by_language == {}

    def test_file_instead_of_directory(self, tmp_path: Path) -> None:
        """Passing a file path instead of a directory returns an empty result."""
        file_path = tmp_path / "not_a_dir.py"
        file_path.write_text("print('hello')\n")

        result = analyze_languages(file_path)

        assert result.primary_language is None
        assert result.total_loc == 0
        assert result.file_count == 0


# ---------------------------------------------------------------------------
# TestDataStructures
# ---------------------------------------------------------------------------


class TestDataStructures:
    """Tests for data structure integrity."""

    def test_result_is_frozen(self) -> None:
        """``LanguageBreakdownResult`` instances are immutable."""
        result = LanguageBreakdownResult(
            primary_language="Python",
            language_percentages={"Python": 1.0},
            lines_by_language={"Python": 10},
            total_loc=10,
            file_count=1,
        )
        with pytest.raises(FrozenInstanceError):
            result.primary_language = "Rust"  # type: ignore[misc]

    def test_extension_map_values_are_strings(self) -> None:
        """All values in ``EXTENSION_LANGUAGE_MAP`` are non-empty strings."""
        for ext, lang in EXTENSION_LANGUAGE_MAP.items():
            assert isinstance(lang, str), f"Value for {ext} is not a string"
            assert len(lang) > 0, f"Value for {ext} is empty"

    def test_extension_map_keys_start_with_dot(self) -> None:
        """All keys in ``EXTENSION_LANGUAGE_MAP`` start with a dot."""
        for ext in EXTENSION_LANGUAGE_MAP:
            assert ext.startswith("."), f"Key {ext!r} does not start with '.'"

    def test_extension_map_keys_are_lowercase(self) -> None:
        """All keys in ``EXTENSION_LANGUAGE_MAP`` are lowercase."""
        for ext in EXTENSION_LANGUAGE_MAP:
            assert ext == ext.lower(), f"Key {ext!r} is not lowercase"


# ---------------------------------------------------------------------------
# TestDeepNesting
# ---------------------------------------------------------------------------


class TestDeepNesting:
    """Tests for files in deeply nested directory structures."""

    def test_deeply_nested_source_files(self, tmp_path: Path) -> None:
        """A file at ``a/b/c/d/e/main.py`` is counted."""
        _make_project(tmp_path, {"a/b/c/d/e/main.py": _lines(7)})

        result = analyze_languages(tmp_path)

        assert result.total_loc == 7
        assert result.file_count == 1
        assert result.primary_language == "Python"

    def test_mixed_depths(self, tmp_path: Path) -> None:
        """Files at root, 1 level, and 3 levels deep are all counted."""
        _make_project(
            tmp_path,
            {
                "root.py": _lines(2),
                "src/level1.py": _lines(3),
                "src/deep/nested/level3.py": _lines(5),
            },
        )

        result = analyze_languages(tmp_path)

        assert result.total_loc == 10
        assert result.file_count == 3
        assert result.lines_by_language == {"Python": 10}
