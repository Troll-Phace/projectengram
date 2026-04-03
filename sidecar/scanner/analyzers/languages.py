"""Language analysis via file extension mapping and line counting.

Walks a project directory tree, counts lines of code per file extension,
maps extensions to canonical language names using the shared extension
map, computes percentage breakdowns, and determines the primary language.

Config-format files (JSON, YAML, etc.) are excluded entirely — only
extensions present in ``EXTENSION_LANGUAGE_MAP`` are counted.

This module is pure: it performs filesystem I/O (reading source files)
but NO database I/O.  The caller (orchestrator) is responsible for
persisting results.

Reference: ARCHITECTURE.md §5.3 — Phase 2c: Language & LOC Analysis.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from scanner.analyzers._constants import EXTENSION_LANGUAGE_MAP, is_excluded_dir

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LanguageBreakdownResult:
    """Result of language analysis for a project directory.

    Attributes:
        primary_language: The language with the most lines of code,
            excluding config formats (JSON, YAML, etc.).  ``None`` if
            no recognised source files were found.
        language_percentages: Mapping of language name to its
            percentage share of total LOC (0.0--1.0).  Sorted by
            percentage descending.  Empty dict if no source files.
        lines_by_language: Mapping of language name to raw line
            count.  Includes only languages mapped via
            ``EXTENSION_LANGUAGE_MAP``.
        total_loc: Total lines of code across all recognised languages.
        file_count: Number of recognised source files analysed.
    """

    primary_language: str | None
    language_percentages: dict[str, float]
    lines_by_language: dict[str, int]
    total_loc: int
    file_count: int


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _count_lines(file_path: Path) -> int:
    """Count lines in a text file, returning 0 on any error.

    Attempts UTF-8 first, then falls back to latin-1 (which never
    fails for single-byte data).  Returns 0 for unreadable files.

    Args:
        file_path: Absolute path to the file.

    Returns:
        The number of lines in the file, or 0 if the file cannot
        be read.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except UnicodeDecodeError:
        try:
            with open(file_path, "r", encoding="latin-1") as f:
                return sum(1 for _ in f)
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            return 0
    except (FileNotFoundError, PermissionError, OSError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_languages(project_dir: Path) -> LanguageBreakdownResult:
    """Analyse language composition of a project directory.

    Walks the directory tree (pruning excluded directories such as
    ``node_modules`` and ``.git``), counts lines per recognised file
    extension, and computes percentage breakdowns.

    Only extensions present in ``EXTENSION_LANGUAGE_MAP`` are counted.
    Config-format files (JSON, YAML, TOML, etc.) are excluded because
    they are not present in the language map.

    Args:
        project_dir: Resolved absolute path to the project directory.

    Returns:
        A ``LanguageBreakdownResult`` with line counts, percentages,
        and primary language.  Returns an empty result if the
        directory does not exist or contains no recognised source
        files.
    """
    if not project_dir.is_dir():
        return LanguageBreakdownResult(
            primary_language=None,
            language_percentages={},
            lines_by_language={},
            total_loc=0,
            file_count=0,
        )

    lines_by_language: dict[str, int] = {}
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(project_dir):
        # Prune excluded directories in-place.
        dirnames[:] = sorted(d for d in dirnames if not is_excluded_dir(d))

        for filename in filenames:
            ext = Path(filename).suffix.lower()
            language = EXTENSION_LANGUAGE_MAP.get(ext)
            if language is None:
                continue

            full_path = os.path.join(dirpath, filename)
            line_count = _count_lines(Path(full_path))

            lines_by_language[language] = (
                lines_by_language.get(language, 0) + line_count
            )
            file_count += 1

    total_loc = sum(lines_by_language.values())

    if total_loc == 0:
        return LanguageBreakdownResult(
            primary_language=None,
            language_percentages={},
            lines_by_language=lines_by_language,
            total_loc=0,
            file_count=file_count,
        )

    # Compute percentages and sort descending by value, then
    # alphabetically by language name for deterministic tie-breaking.
    language_percentages = dict(
        sorted(
            (
                (lang, round(count / total_loc, 4))
                for lang, count in lines_by_language.items()
            ),
            key=lambda x: (-x[1], x[0]),
        )
    )

    # Primary language is simply the one with the highest LOC.
    # Config formats are already excluded by the extension map.
    primary_language = max(lines_by_language, key=lines_by_language.get)  # type: ignore[arg-type]

    return LanguageBreakdownResult(
        primary_language=primary_language,
        language_percentages=language_percentages,
        lines_by_language=lines_by_language,
        total_loc=total_loc,
        file_count=file_count,
    )
