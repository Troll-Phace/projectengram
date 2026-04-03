"""Scanner analyzer modules for per-project analysis.

Each analyzer is a pure module that accepts a project directory path
and returns a frozen dataclass result.  Analyzers perform filesystem
I/O but no database I/O — the caller (orchestrator) is responsible
for persisting results.

Available analyzers:

* **project_type** — detect project types from manifest files.
* **frameworks** — detect frameworks and tooling from deps and
  config file presence.
"""

from scanner.analyzers.frameworks import (
    FrameworkDetectionResult,
    detect_frameworks,
)
from scanner.analyzers.project_type import (
    ManifestInfo,
    ProjectTypeResult,
    detect_project_type,
)

__all__ = [
    "FrameworkDetectionResult",
    "ManifestInfo",
    "ProjectTypeResult",
    "detect_frameworks",
    "detect_project_type",
]
