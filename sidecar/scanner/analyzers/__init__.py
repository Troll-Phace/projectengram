"""Scanner analyzer modules for per-project analysis.

Each analyzer is a pure module that accepts a project directory path
and returns a frozen dataclass result.  Analyzers perform filesystem
I/O but no database I/O — the caller (orchestrator) is responsible
for persisting results.

Available analyzers:

* **project_type** — detect project types from manifest files.
* **frameworks** — detect frameworks and tooling from deps and
  config file presence.
* **languages** — count lines of code per language and compute
  percentage breakdowns.
* **git_analyzer** — extract git metadata (branch, dirty status,
  last commit, branch count, remote URL).
* **size** — compute total size and file counts for a project.
"""

from scanner.analyzers.frameworks import (
    FrameworkDetectionResult,
    detect_frameworks,
)
from scanner.analyzers.git_analyzer import GitAnalysisResult, analyze_git
from scanner.analyzers.languages import (
    LanguageBreakdownResult,
    analyze_languages,
)
from scanner.analyzers.project_type import (
    ManifestInfo,
    ProjectTypeResult,
    detect_project_type,
)
from scanner.analyzers.size import SizeResult, compute_size

__all__ = [
    "FrameworkDetectionResult",
    "GitAnalysisResult",
    "LanguageBreakdownResult",
    "ManifestInfo",
    "ProjectTypeResult",
    "SizeResult",
    "analyze_git",
    "analyze_languages",
    "compute_size",
    "detect_frameworks",
    "detect_project_type",
]
