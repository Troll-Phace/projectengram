"""Shared constants for scanner analyzer modules.

Provides directory exclusion sets, file extension-to-language mappings,
and source/config extension sets used by the language analyzer and size
analyzer modules during project tree walks.

This module is pure: no I/O, no database access, no side effects.
All exports are constants or a single pure helper function.
"""

# ---------------------------------------------------------------------------
# Excluded directories
# ---------------------------------------------------------------------------

EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        "target",
        "dist",
        "build",
        "__pycache__",
        "venv",
        ".venv",
        "env",
        ".env",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".next",
        ".nuxt",
        "vendor",
        "bower_components",
        "coverage",
        ".coverage",
        "htmlcov",
        ".eggs",
    }
)
"""Directories to skip during file tree walks.

Uses ``frozenset`` for O(1) membership checks.  Entries are matched
against directory *basenames*, not full paths.
"""

# ---------------------------------------------------------------------------
# Extension → language mapping
# ---------------------------------------------------------------------------

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    # Python
    ".py": "Python",
    ".pyi": "Python",
    ".pyx": "Python",
    # TypeScript
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    # JavaScript
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    # Rust
    ".rs": "Rust",
    # Go
    ".go": "Go",
    # Java
    ".java": "Java",
    # C
    ".c": "C",
    ".h": "C",
    # C++
    ".cpp": "C++",
    ".cxx": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".hxx": "C++",
    ".hh": "C++",
    # C#
    ".cs": "C#",
    # Ruby
    ".rb": "Ruby",
    ".erb": "Ruby",
    # PHP
    ".php": "PHP",
    # Swift
    ".swift": "Swift",
    # Kotlin
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    # Dart
    ".dart": "Dart",
    # Elixir
    ".ex": "Elixir",
    ".exs": "Elixir",
    # HTML
    ".html": "HTML",
    ".htm": "HTML",
    # CSS
    ".css": "CSS",
    # SCSS
    ".scss": "SCSS",
    ".sass": "SCSS",
    # SQL
    ".sql": "SQL",
    # Shell
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".fish": "Shell",
    # Lua
    ".lua": "Lua",
    # R
    ".r": "R",
    # Scala
    ".scala": "Scala",
    ".sc": "Scala",
    # Perl
    ".pl": "Perl",
    ".pm": "Perl",
    # Haskell
    ".hs": "Haskell",
    ".lhs": "Haskell",
    # Vue
    ".vue": "Vue",
    # Svelte
    ".svelte": "Svelte",
    # Markdown
    ".md": "Markdown",
    ".mdx": "Markdown",
    # Zig
    ".zig": "Zig",
    # Nim
    ".nim": "Nim",
    # OCaml
    ".ml": "OCaml",
    ".mli": "OCaml",
    # Clojure
    ".clj": "Clojure",
    ".cljs": "Clojure",
    ".cljc": "Clojure",
}
"""Maps lowercase file extensions (with leading dot) to canonical language names.

Callers should normalise the extension to lowercase before lookup
(e.g. ``suffix.lower()``).
"""

# ---------------------------------------------------------------------------
# Config & source extension sets
# ---------------------------------------------------------------------------

CONFIG_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".ini",
        ".cfg",
        ".env",
        ".properties",
        ".lock",
    }
)
"""Extensions that are tracked for LOC but excluded from ``primary_language``
determination.  These are config/data files, not source code.
"""

SOURCE_EXTENSIONS: frozenset[str] = frozenset(EXTENSION_LANGUAGE_MAP.keys()) | CONFIG_EXTENSIONS
"""Union of language-mapped extensions and config extensions.

Defines what counts as a "source file" for file-counting purposes.
"""


# ---------------------------------------------------------------------------
# Helper function
# ---------------------------------------------------------------------------


def is_excluded_dir(name: str) -> bool:
    """Check whether a directory name should be excluded from tree walks.

    Checks against the ``EXCLUDED_DIRS`` set and handles special
    patterns such as ``.egg-info`` suffixed directories.

    Args:
        name: The directory basename (not the full path).

    Returns:
        ``True`` if the directory should be skipped during traversal.
    """
    return name in EXCLUDED_DIRS or name.endswith(".egg-info")
