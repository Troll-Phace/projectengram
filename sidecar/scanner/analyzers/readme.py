"""README extraction for project directories.

Finds the project README file (case-insensitive, with extension priority
ordering), extracts the first paragraph of prose after skipping the H1
title, badge lines, and images, and truncates to 300 characters.  Falls
back to a manifest description supplied by the caller when no README
prose is available.

This module is pure: it performs filesystem I/O (reading README files)
but NO database I/O.  The caller (orchestrator) is responsible for
persisting results.

Reference: ARCHITECTURE.md §5.3 — Phase 2e: README Extraction.
"""

import os
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_SNIPPET_LENGTH: int = 300
"""Maximum number of characters in a description snippet."""

_README_EXTENSIONS_PRIORITY: list[str] = [".md", ".rst", ".txt", ""]
"""File extensions to check, in descending priority order.

Markdown (``.md``) is the most common README format in modern projects.
reStructuredText (``.rst``) is common in the Python ecosystem.  Plain
text (``.txt``) and extensionless ``README`` are legacy but still seen.
"""

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadmeResult:
    """Result of README extraction for a project directory.

    Attributes:
        snippet: Extracted description text, truncated to at most
            ``_MAX_SNIPPET_LENGTH`` characters.  ``None`` when no
            description could be extracted from any source.
        source: Provenance indicator — ``"readme"`` if the snippet came
            from a README file, ``"manifest"`` if it came from the
            caller-supplied manifest description, or ``None`` when no
            description was found.
    """

    snippet: str | None
    source: str | None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _safe_read_text(path: Path) -> str | None:
    """Read file as UTF-8 text, returning ``None`` on any I/O or encoding error.

    Args:
        path: Absolute path to the file.

    Returns:
        The file contents as a string, or ``None`` if reading failed.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, UnicodeDecodeError, OSError):
        return None


def _find_readme(project_dir: Path) -> Path | None:
    """Locate the best README file in *project_dir* using case-insensitive matching.

    Performs a single ``os.listdir`` call and builds a lowercase lookup
    table.  Extensions are checked in priority order (``.md`` > ``.rst``
    > ``.txt`` > no extension) and the first match that is a regular
    file is returned.

    Args:
        project_dir: Path to the project root directory.

    Returns:
        The ``Path`` to the best matching README file, or ``None`` if
        no suitable file is found.
    """
    try:
        entries = os.listdir(project_dir)
    except OSError:
        return None

    # Build a mapping of lowercase name -> actual filesystem name for
    # entries whose lowercase form starts with "readme".
    lower_to_actual: dict[str, str] = {}
    for entry in entries:
        if entry.lower().startswith("readme"):
            lower_to_actual[entry.lower()] = entry

    if not lower_to_actual:
        return None

    # Check extensions in priority order.
    for ext in _README_EXTENSIONS_PRIORITY:
        target = f"readme{ext}"
        actual_name = lower_to_actual.get(target)
        if actual_name is not None:
            candidate = project_dir / actual_name
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue

    return None


def _extract_first_paragraph(content: str) -> str | None:
    """Extract the first paragraph of prose from README content.

    Applies a two-phase line scan:

    1. **Header zone** (``skipping_header=True``): skips the H1 title
       (ATX ``# Title`` and setext ``Title\\n====``), badge/image lines,
       HTML badge lines, and blank lines.  Setext titles are detected
       by buffering each candidate prose line and checking whether the
       *next* line is an underline of ``=`` or ``-`` chars.  The first
       non-skippable, non-heading line transitions to the prose-
       collection phase.
    2. **Prose zone** (``skipping_header=False``): collects consecutive
       non-blank, non-heading lines until a blank line or heading is
       encountered.

    Args:
        content: Full text content of the README file.

    Returns:
        The extracted paragraph as a single string with internal
        whitespace normalised, or ``None`` if no prose paragraph
        could be identified.
    """
    lines = content.splitlines()
    skipping_header = True
    paragraph_lines: list[str] = []

    # In the header zone we buffer a candidate prose line so we can
    # check whether the *following* line is a setext underline, which
    # would indicate the candidate is actually a title and should be
    # discarded.
    pending_line: str | None = None

    for line in lines:
        stripped = line.strip()

        # --- Helper: is this line a setext underline? --------------------
        is_eq_underline = bool(stripped) and all(ch == "=" for ch in stripped)
        is_dash_underline = len(stripped) >= 3 and all(
            ch == "-" for ch in stripped
        )

        if skipping_header:
            # If we have a pending candidate and the current line is a
            # setext underline, both form a setext heading — discard.
            if pending_line is not None:
                if is_eq_underline or is_dash_underline:
                    # Setext heading: discard the title + underline.
                    pending_line = None
                    continue
                # Not an underline — the pending line was real prose.
                skipping_header = False
                paragraph_lines.append(pending_line)
                pending_line = None
                # Fall through to handle current line in prose zone.
                if not stripped or stripped.startswith("#"):
                    break
                paragraph_lines.append(stripped)
                continue

            # Skip blank lines in the header zone.
            if not stripped:
                continue

            # Skip ATX heading lines (any level: #, ##, ###, etc.).
            if stripped.startswith("#"):
                continue

            # Skip standalone setext underlines (no preceding title
            # text — acts as a horizontal rule).
            if is_eq_underline or is_dash_underline:
                continue

            # Skip badge lines (start with `[![`).
            if stripped.startswith("[!["):
                continue

            # Skip image-only lines (Markdown images: `![alt](url)`).
            if stripped.startswith("![") and "](" in stripped:
                continue

            # Skip HTML badge/image lines.
            stripped_lower = stripped.lower()
            if stripped_lower.startswith(("<a ", "<img ")):
                continue
            if stripped_lower.startswith("<p") and (
                "<img" in stripped_lower or "badge" in stripped_lower
            ):
                continue

            # Candidate prose line — buffer it in case the next line
            # turns out to be a setext underline.
            pending_line = stripped
        else:
            # In the prose zone: stop on blank line or heading.
            if not stripped or stripped.startswith("#"):
                break
            paragraph_lines.append(stripped)

    # If a candidate prose line was still pending when the loop ended
    # (e.g. the README ends right after a single prose line with no
    # following underline), treat it as real prose.
    if pending_line is not None:
        paragraph_lines.append(pending_line)

    text = " ".join(paragraph_lines).strip()
    return text if text else None


def _truncate(text: str, max_length: int) -> str:
    """Truncate *text* to *max_length* characters, appending an ellipsis if needed.

    When truncation is necessary the result is exactly *max_length*
    characters long: ``max_length - 1`` characters of the original text
    followed by a single Unicode ellipsis character (U+2026).

    Args:
        text: The string to truncate.
        max_length: Maximum allowed length of the returned string.

    Returns:
        The original string if it fits, otherwise the truncated string
        with a trailing ellipsis.
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "\u2026"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_readme(
    project_dir: Path,
    manifest_description: str | None = None,
) -> ReadmeResult:
    """Extract a description snippet for the project at *project_dir*.

    Implements a two-level fallback chain:

    1. Find and parse a README file — extract the first paragraph of
       prose after the title and badges, truncate to 300 characters.
    2. If no README prose is available, fall back to the caller-supplied
       *manifest_description* (typically from ``package.json`` or
       ``Cargo.toml``).
    3. If neither source yields a description, return an empty result.

    Args:
        project_dir: Path to the project root directory.
        manifest_description: Optional description string previously
            extracted from a project manifest file (e.g. the
            ``description`` field of ``package.json``).  Used as a
            fallback when no README prose is available.

    Returns:
        A ``ReadmeResult`` indicating the extracted snippet and its
        provenance.
    """
    # --- Attempt 1: README file ------------------------------------------
    readme_path = _find_readme(project_dir)
    if readme_path is not None:
        content = _safe_read_text(readme_path)
        if content is not None:
            paragraph = _extract_first_paragraph(content)
            if paragraph:
                snippet = _truncate(paragraph, _MAX_SNIPPET_LENGTH)
                return ReadmeResult(snippet=snippet, source="readme")

    # --- Attempt 2: Manifest description ---------------------------------
    if manifest_description is not None:
        cleaned = manifest_description.strip()
        if cleaned:
            snippet = _truncate(cleaned, _MAX_SNIPPET_LENGTH)
            return ReadmeResult(snippet=snippet, source="manifest")

    # --- No description available ----------------------------------------
    return ReadmeResult(snippet=None, source=None)
