"""Framework and tooling detection from dependencies and config files.

Detects frameworks and tools by combining two strategies:

1. **Dependency scanning** — checks parsed dependency lists from
   manifest files for known framework packages.
2. **File presence** — checks for config files and directories that
   indicate specific frameworks or tools.

This module is pure: it performs filesystem I/O (checking file/directory
existence) but NO database I/O.  The caller (orchestrator) is
responsible for persisting results.

Reference: ARCHITECTURE.md §5.3 — Phase 2b: Framework & Tooling Detection.
"""

from dataclasses import dataclass
from pathlib import Path

from scanner.analyzers.project_type import ProjectTypeResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEPENDENCY_SIGNALS: list[tuple[str, str]] = [
    # (dependency_name, framework_label)
    ("react", "react"),
    ("react-dom", "react"),
    ("@tauri-apps/api", "tauri"),
    ("@tauri-apps/cli", "tauri"),
    ("tailwindcss", "tailwind-css"),
    ("fastapi", "fastapi"),
    ("django", "django"),
    ("flask", "flask"),
    ("express", "express"),
    ("next", "nextjs"),
    ("nuxt", "nuxt"),
    ("vue", "vue"),
    ("svelte", "svelte"),
    ("@angular/core", "angular"),
    ("actix-web", "actix"),
    ("axum", "axum"),
    ("rocket", "rocket"),
    ("github.com/gin-gonic/gin", "gin"),
    ("gin-gonic/gin", "gin"),
    ("sqlmodel", "sqlmodel"),
    ("sqlalchemy", "sqlalchemy"),
    ("prisma", "prisma"),
    ("drizzle-orm", "drizzle"),
]
"""Mapping from dependency names to framework labels.

Each entry is a ``(dependency_name, framework_label)`` tuple.  If
``dependency_name`` appears anywhere in the project's unified dependency
set (runtime + dev), the corresponding ``framework_label`` is added to
the detection result.
"""

FILE_SIGNALS: list[tuple[str, str, str]] = [
    # (pattern, signal_type, framework_label)
    ("vite.config.*", "glob", "vite"),
    ("tsconfig.json", "file", "typescript"),
    (".github/workflows", "dir", "github-actions"),
    ("Dockerfile", "file", "docker"),
    ("docker-compose.yml", "file", "docker"),
    ("docker-compose.yaml", "file", "docker"),
    (".dockerignore", "file", "docker"),
    ("tailwind.config.*", "glob", "tailwind-css"),
    ("next.config.*", "glob", "nextjs"),
    ("nuxt.config.*", "glob", "nuxt"),
    (".eslintrc*", "glob", "eslint"),
    ("eslint.config.*", "glob", "eslint"),
    ("prettier.config.*", "glob", "prettier"),
    (".prettierrc*", "glob", "prettier"),
    ("jest.config.*", "glob", "jest"),
    ("vitest.config.*", "glob", "vitest"),
    ("playwright.config.*", "glob", "playwright"),
    (".storybook", "dir", "storybook"),
]
"""Mapping from filesystem patterns to framework labels.

Each entry is a ``(pattern, signal_type, framework_label)`` tuple.

``signal_type`` determines how the pattern is checked:

* ``"file"`` — ``(project_dir / pattern).is_file()``
* ``"dir"`` — ``(project_dir / pattern).is_dir()``
* ``"glob"`` — ``any(project_dir.glob(pattern))``
"""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameworkDetectionResult:
    """Result of framework and tooling detection.

    Attributes:
        frameworks: Sorted, deduplicated list of detected framework
            and tool names.  All names are lowercase with hyphens
            (e.g. ``"tailwind-css"``, ``"github-actions"``).
    """

    frameworks: list[str]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_frameworks(
    project_dir: Path,
    project_type_result: ProjectTypeResult,
) -> FrameworkDetectionResult:
    """Detect frameworks and tooling from dependencies and config files.

    Combines two detection strategies:

    1. **Dependency scanning** — checks parsed dependency lists from
       the project type result for known framework packages.
    2. **File presence** — checks for config files and directories
       that indicate specific frameworks or tools.

    Args:
        project_dir: Resolved absolute path to the project directory.
        project_type_result: Output from ``detect_project_type``,
            providing parsed dependency lists.

    Returns:
        A ``FrameworkDetectionResult`` with a sorted, deduplicated
        list of detected framework names.
    """
    detected: set[str] = set()

    # 1. Dependency signals — check against the unified dependency set.
    all_deps = project_type_result.all_dependencies
    for dep_name, framework_label in DEPENDENCY_SIGNALS:
        if dep_name in all_deps:
            detected.add(framework_label)

    # 2. File signals — check for config files and directories.
    for pattern, signal_type, framework_label in FILE_SIGNALS:
        try:
            if signal_type == "file":
                if (project_dir / pattern).is_file():
                    detected.add(framework_label)
            elif signal_type == "dir":
                if (project_dir / pattern).is_dir():
                    detected.add(framework_label)
            elif signal_type == "glob":
                if any(project_dir.glob(pattern)):
                    detected.add(framework_label)
        except OSError:
            # Permission-denied or other OS-level errors should not
            # crash detection — skip this signal and continue.
            continue

    return FrameworkDetectionResult(frameworks=sorted(detected))
