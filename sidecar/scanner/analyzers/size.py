"""Size computation for project directories.

Walks a project directory tree and computes total file size in bytes,
total file count, and source file count (files with recognised source
code or config extensions).  Vendored and build directories are pruned
via the shared ``is_excluded_dir`` helper.

This module is pure: it performs filesystem I/O (reading file sizes)
but NO database I/O.  The caller (orchestrator) is responsible for
persisting results.

Reference: ARCHITECTURE.md §5.3 — Phase 2f: Size Computation.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from scanner.analyzers._constants import SOURCE_EXTENSIONS, is_excluded_dir

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SizeResult:
    """Result of size computation for a project directory.

    Attributes:
        size_bytes: Total size of all files in bytes, excluding
            vendored and build directories.
        file_count: Total number of files (all types, not just
            source code).
        source_file_count: Number of files with recognised source
            code or config extensions.
    """

    size_bytes: int
    file_count: int
    source_file_count: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_size(project_dir: Path) -> SizeResult:
    """Compute total size and file counts for a project directory.

    Walks the file tree with excluded directories pruned in-place.
    Sums file sizes reported by ``os.path.getsize()`` and counts
    files by extension category.

    Args:
        project_dir: Path to the project directory.  Does not need
            to be pre-resolved — the function handles resolution.

    Returns:
        A ``SizeResult`` with total bytes and file counts.  Returns
        a zero-valued result if the directory does not exist or is
        not a directory.
    """
    resolved = project_dir.resolve()

    if not resolved.is_dir():
        return SizeResult(0, 0, 0)

    size_bytes = 0
    file_count = 0
    source_file_count = 0

    for dirpath, dirnames, filenames in os.walk(resolved):
        # Prune excluded directories in-place and sort for
        # deterministic traversal order.
        dirnames[:] = [d for d in dirnames if not is_excluded_dir(d)]
        dirnames.sort()

        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            try:
                file_size = os.path.getsize(full_path)
            except OSError:
                # Permission errors, broken symlinks, etc.
                continue

            size_bytes += file_size
            file_count += 1

            ext = Path(filename).suffix.lower()
            if ext in SOURCE_EXTENSIONS:
                source_file_count += 1

    return SizeResult(size_bytes, file_count, source_file_count)
