"""Tests for the README extraction module of the Engram scanning pipeline.

Validates README file discovery (extension priority, case insensitivity),
prose paragraph extraction (skipping titles, badges, images), truncation
to the maximum snippet length, manifest description fallback, source field
correctness, the frozen dataclass contract, and edge cases such as
non-existent directories, Unicode content, and badge-only files.

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

from scanner.analyzers.readme import (  # noqa: E402
    ReadmeResult,
    _MAX_SNIPPET_LENGTH,
    extract_readme,
)


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


# ---------------------------------------------------------------------------
# TestReadmeDiscovery
# ---------------------------------------------------------------------------


class TestReadmeDiscovery:
    """Tests for README file finding logic and extension priority."""

    def test_finds_readme_md(self, tmp_path: Path) -> None:
        """A project with ``README.md`` is discovered and its prose extracted."""
        _make_file(tmp_path / "README.md", "# Title\n\nFrom the markdown file.")

        result = extract_readme(tmp_path)

        assert result.snippet == "From the markdown file."
        assert result.source == "readme"

    def test_finds_readme_rst(self, tmp_path: Path) -> None:
        """``README.rst`` is found when no ``.md`` variant exists."""
        _make_file(
            tmp_path / "README.rst",
            "Title\n=====\n\nFrom the rst file.",
        )

        result = extract_readme(tmp_path)

        assert result.snippet == "From the rst file."
        assert result.source == "readme"

    def test_finds_readme_txt(self, tmp_path: Path) -> None:
        """``README.txt`` is found when no ``.md`` or ``.rst`` variants exist."""
        _make_file(tmp_path / "README.txt", "From the txt file.")

        result = extract_readme(tmp_path)

        assert result.snippet == "From the txt file."
        assert result.source == "readme"

    def test_finds_readme_no_extension(self, tmp_path: Path) -> None:
        """A bare ``README`` (no extension) is found when no other variants exist."""
        _make_file(tmp_path / "README", "From the extensionless file.")

        result = extract_readme(tmp_path)

        assert result.snippet == "From the extensionless file."
        assert result.source == "readme"

    def test_md_preferred_over_rst(self, tmp_path: Path) -> None:
        """``.md`` takes priority over ``.rst`` when both exist."""
        _make_file(tmp_path / "README.md", "# Title\n\nFrom the markdown file.")
        _make_file(
            tmp_path / "README.rst",
            "Title\n=====\n\nFrom the rst file.",
        )

        result = extract_readme(tmp_path)

        assert result.snippet == "From the markdown file."
        assert result.source == "readme"

    def test_case_insensitive_lowercase(self, tmp_path: Path) -> None:
        """A fully lowercase ``readme.md`` is discovered."""
        _make_file(tmp_path / "readme.md", "# Title\n\nLowercase readme found.")

        result = extract_readme(tmp_path)

        assert result.snippet == "Lowercase readme found."
        assert result.source == "readme"

    def test_case_insensitive_mixed(self, tmp_path: Path) -> None:
        """A mixed-case ``Readme.md`` is discovered."""
        _make_file(tmp_path / "Readme.md", "# Title\n\nMixed case readme found.")

        result = extract_readme(tmp_path)

        assert result.snippet == "Mixed case readme found."
        assert result.source == "readme"

    def test_no_readme_file(self, tmp_path: Path) -> None:
        """An empty directory with no manifest yields snippet=None, source=None."""
        result = extract_readme(tmp_path)

        assert result.snippet is None
        assert result.source is None


# ---------------------------------------------------------------------------
# TestProseParsing
# ---------------------------------------------------------------------------


class TestProseParsing:
    """Tests for prose paragraph extraction from README content."""

    def test_standard_readme(self, tmp_path: Path) -> None:
        """Full README with title, badge lines, then prose extracts the first prose paragraph."""
        content = (
            "# My Project\n"
            "\n"
            "[![CI](https://img.shields.io/badge/ci-passing-green)](https://ci.example.com)\n"
            "[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)\n"
            "\n"
            "A powerful tool for analyzing codebases and generating visual dependency graphs.\n"
            "\n"
            "## Installation\n"
            "\n"
            "pip install my-project\n"
        )
        _make_file(tmp_path / "README.md", content)

        result = extract_readme(tmp_path)

        assert result.snippet == (
            "A powerful tool for analyzing codebases and generating "
            "visual dependency graphs."
        )
        assert result.source == "readme"

    def test_prose_after_title_no_badges(self, tmp_path: Path) -> None:
        """Title followed immediately by prose (no badges) extracts the prose."""
        content = "# Simple Project\n\nThis project does simple things well.\n"
        _make_file(tmp_path / "README.md", content)

        result = extract_readme(tmp_path)

        assert result.snippet == "This project does simple things well."
        assert result.source == "readme"

    def test_badges_only_no_prose(self, tmp_path: Path) -> None:
        """README with only title and badges yields no prose snippet."""
        content = (
            "# Badge Project\n"
            "\n"
            "[![CI](https://img.shields.io/badge/ci-passing-green)](https://ci.example.com)\n"
            "[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)\n"
        )
        _make_file(tmp_path / "README.md", content)

        result = extract_readme(tmp_path)

        assert result.snippet is None
        assert result.source is None

    def test_empty_readme(self, tmp_path: Path) -> None:
        """An empty README file yields snippet=None."""
        _make_file(tmp_path / "README.md", "")

        result = extract_readme(tmp_path)

        assert result.snippet is None

    def test_title_only(self, tmp_path: Path) -> None:
        """A README with only a title heading yields snippet=None."""
        _make_file(tmp_path / "README.md", "# Just a Title\n")

        result = extract_readme(tmp_path)

        assert result.snippet is None

    def test_multiple_paragraphs_takes_first(self, tmp_path: Path) -> None:
        """When multiple prose paragraphs exist, only the first is returned."""
        content = (
            "# Project\n"
            "\n"
            "First paragraph of prose.\n"
            "\n"
            "Second paragraph should be ignored.\n"
        )
        _make_file(tmp_path / "README.md", content)

        result = extract_readme(tmp_path)

        assert result.snippet == "First paragraph of prose."
        assert result.source == "readme"

    def test_skips_setext_h1_underline(self, tmp_path: Path) -> None:
        """A setext-style title with ``===`` underline is skipped, prose is extracted."""
        content = (
            "My Project\n"
            "==========\n"
            "\n"
            "This is the description.\n"
        )
        _make_file(tmp_path / "README.md", content)

        result = extract_readme(tmp_path)

        assert result.snippet == "This is the description."
        assert result.source == "readme"

    def test_skips_html_badges(self, tmp_path: Path) -> None:
        """HTML badge lines (``<img>`` and ``<a>`` tags) are skipped, prose is extracted."""
        content = (
            "# Project\n"
            "\n"
            '<a href="https://ci.example.com"><img src="https://img.shields.io/badge/ci-passing-green" /></a>\n'
            '<img src="https://img.shields.io/badge/coverage-95%25-brightgreen" />\n'
            "\n"
            "A real description of the project.\n"
        )
        _make_file(tmp_path / "README.md", content)

        result = extract_readme(tmp_path)

        assert result.snippet == "A real description of the project."
        assert result.source == "readme"


# ---------------------------------------------------------------------------
# TestTruncation
# ---------------------------------------------------------------------------


class TestTruncation:
    """Tests for snippet truncation at the maximum length boundary."""

    def test_short_paragraph_not_truncated(self, tmp_path: Path) -> None:
        """A 50-character paragraph is returned as-is without truncation."""
        prose = "A" * 50
        _make_file(tmp_path / "README.md", f"# Title\n\n{prose}\n")

        result = extract_readme(tmp_path)

        assert result.snippet == prose
        assert len(result.snippet) == 50

    def test_long_paragraph_truncated_with_ellipsis(self, tmp_path: Path) -> None:
        """A 400-character paragraph is truncated to 300 chars (299 + ellipsis)."""
        prose = "A" * 400
        _make_file(tmp_path / "README.md", f"# Title\n\n{prose}\n")

        result = extract_readme(tmp_path)

        assert result.snippet is not None
        assert len(result.snippet) == _MAX_SNIPPET_LENGTH
        assert result.snippet.endswith("\u2026")
        assert result.snippet == "A" * 299 + "\u2026"

    def test_exactly_300_chars_not_truncated(self, tmp_path: Path) -> None:
        """A paragraph of exactly 300 characters is returned unchanged."""
        prose = "B" * 300
        _make_file(tmp_path / "README.md", f"# Title\n\n{prose}\n")

        result = extract_readme(tmp_path)

        assert result.snippet == prose
        assert len(result.snippet) == 300

    def test_301_chars_truncated(self, tmp_path: Path) -> None:
        """A 301-character paragraph is truncated to 299 chars + ellipsis = 300 total."""
        prose = "C" * 301
        _make_file(tmp_path / "README.md", f"# Title\n\n{prose}\n")

        result = extract_readme(tmp_path)

        assert result.snippet is not None
        assert len(result.snippet) == _MAX_SNIPPET_LENGTH
        assert result.snippet == "C" * 299 + "\u2026"


# ---------------------------------------------------------------------------
# TestManifestFallback
# ---------------------------------------------------------------------------


class TestManifestFallback:
    """Tests for manifest description fallback when README prose is unavailable."""

    def test_no_readme_uses_manifest(self, tmp_path: Path) -> None:
        """No README file with a manifest description yields source='manifest'."""
        result = extract_readme(tmp_path, manifest_description="A CLI tool")

        assert result.snippet == "A CLI tool"
        assert result.source == "manifest"

    def test_empty_readme_uses_manifest(self, tmp_path: Path) -> None:
        """An empty README file falls back to the manifest description."""
        _make_file(tmp_path / "README.md", "")

        result = extract_readme(tmp_path, manifest_description="Manifest desc")

        assert result.snippet == "Manifest desc"
        assert result.source == "manifest"

    def test_badges_only_uses_manifest(self, tmp_path: Path) -> None:
        """A README with only badges and no prose falls back to the manifest."""
        content = (
            "# Badge Project\n"
            "\n"
            "[![CI](https://img.shields.io/badge/ci-passing-green)](https://ci.example.com)\n"
        )
        _make_file(tmp_path / "README.md", content)

        result = extract_readme(tmp_path, manifest_description="From manifest")

        assert result.snippet == "From manifest"
        assert result.source == "manifest"

    def test_no_readme_no_manifest_returns_none(self, tmp_path: Path) -> None:
        """No README and no manifest yields snippet=None, source=None."""
        result = extract_readme(tmp_path, manifest_description=None)

        assert result.snippet is None
        assert result.source is None

    def test_manifest_description_truncated(self, tmp_path: Path) -> None:
        """A manifest description exceeding 300 chars is truncated with ellipsis."""
        long_desc = "D" * 400
        result = extract_readme(tmp_path, manifest_description=long_desc)

        assert result.snippet is not None
        assert len(result.snippet) == _MAX_SNIPPET_LENGTH
        assert result.snippet == "D" * 299 + "\u2026"
        assert result.source == "manifest"


# ---------------------------------------------------------------------------
# TestSourceField
# ---------------------------------------------------------------------------


class TestSourceField:
    """Tests for the ``source`` field of ``ReadmeResult``."""

    def test_source_readme(self, tmp_path: Path) -> None:
        """Prose extracted from a README file sets source='readme'."""
        _make_file(tmp_path / "README.md", "# Title\n\nExtracted from readme.")

        result = extract_readme(tmp_path)

        assert result.source == "readme"

    def test_source_manifest(self, tmp_path: Path) -> None:
        """Fallback to manifest description sets source='manifest'."""
        result = extract_readme(tmp_path, manifest_description="From manifest")

        assert result.source == "manifest"

    def test_source_none(self, tmp_path: Path) -> None:
        """No snippet available sets source=None."""
        result = extract_readme(tmp_path)

        assert result.source is None


# ---------------------------------------------------------------------------
# TestDataStructures
# ---------------------------------------------------------------------------


class TestDataStructures:
    """Tests for the frozen dataclass contract."""

    def test_result_is_frozen(self) -> None:
        """Assigning to ``ReadmeResult.snippet`` raises ``FrozenInstanceError``."""
        result = ReadmeResult(snippet="A description", source="readme")

        with pytest.raises(FrozenInstanceError):
            result.snippet = "modified"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for boundary conditions and unusual inputs."""

    def test_readme_with_only_blank_lines(self, tmp_path: Path) -> None:
        """A README file containing only blank lines yields snippet=None."""
        _make_file(tmp_path / "README.md", "\n\n\n\n")

        result = extract_readme(tmp_path)

        assert result.snippet is None

    def test_unicode_content(self, tmp_path: Path) -> None:
        """README with emoji and non-ASCII characters is extracted correctly."""
        content = "# Projet\n\nUn outil puissant pour les d\u00e9veloppeurs. \U0001f680\n"
        _make_file(tmp_path / "README.md", content)

        result = extract_readme(tmp_path)

        assert result.snippet == "Un outil puissant pour les d\u00e9veloppeurs. \U0001f680"
        assert result.source == "readme"

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        """A path that does not exist returns snippet=None without crashing."""
        result = extract_readme(tmp_path / "nonexistent")

        assert result.snippet is None
        assert result.source is None

    def test_readme_all_badges_and_images(self, tmp_path: Path) -> None:
        """A file with only badge and image lines yields no prose snippet."""
        content = (
            "# Project\n"
            "\n"
            "[![CI](https://img.shields.io/badge/ci-passing-green)](https://ci.example.com)\n"
            "[![Coverage](https://img.shields.io/badge/coverage-90-blue)](https://coverage.example.com)\n"
            "![Logo](https://example.com/logo.png)\n"
            "![Banner](https://example.com/banner.png)\n"
        )
        _make_file(tmp_path / "README.md", content)

        result = extract_readme(tmp_path)

        assert result.snippet is None
