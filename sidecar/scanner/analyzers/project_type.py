"""Project type detection via manifest file scanning.

Scans a project directory for known manifest files (``package.json``,
``Cargo.toml``, ``pyproject.toml``, ``go.mod``, etc.) in priority order.
The first manifest found determines the primary classification, but ALL
manifests are parsed for completeness.  Each parser extracts project
name, description, and dependency lists.

This module is pure: it performs filesystem I/O (reading manifest files)
but NO database I/O.  The caller (orchestrator) is responsible for
persisting results.

Reference: ARCHITECTURE.md §5.3 — Phase 2a: Project Type Detection.
"""

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANIFEST_PRIORITY: list[tuple[str, str]] = [
    ("package.json", "npm"),
    ("Cargo.toml", "cargo"),
    ("pyproject.toml", "pip"),
    ("go.mod", "go"),
    ("requirements.txt", "pip"),
    ("composer.json", "composer"),
    ("Gemfile", "bundler"),
    ("build.gradle", "gradle"),
    ("build.gradle.kts", "gradle"),
    ("pom.xml", "maven"),
    ("Package.swift", "swift"),
    ("mix.exs", "mix"),
    ("pubspec.yaml", "pub"),
]

_PEP508_NAME_RE = re.compile(r"^([a-zA-Z0-9][a-zA-Z0-9._-]*)")
"""Regex to extract the bare package name from a PEP 508 requirement string."""

_GO_MODULE_RE = re.compile(r"^module\s+(.+)$", re.MULTILINE)
"""Regex to extract the module path from a go.mod file."""

_GO_REQUIRE_BLOCK_RE = re.compile(
    r"require\s*\(\s*(.*?)\s*\)", re.DOTALL
)
"""Regex to match require blocks in a go.mod file."""

_GO_SINGLE_REQUIRE_RE = re.compile(
    r"^require\s+(\S+)\s+v\S+", re.MULTILINE
)
"""Regex to match single-line require directives in a go.mod file."""

_GEMFILE_GEM_RE = re.compile(r"""gem\s+['"]([^'"]+)['"]""")
"""Regex to extract gem names from a Gemfile."""

_GRADLE_DEP_RE = re.compile(
    r"(?:implementation|api|testImplementation|compileOnly|runtimeOnly"
    r"|testRuntimeOnly|annotationProcessor|kapt)"
    r"""\s*['"(]([^'"():]+:[^'"():]+)""",
)
"""Regex to extract Gradle dependency declarations."""

_SWIFT_PACKAGE_NAME_RE = re.compile(r'\.package\s*\(\s*name:\s*"([^"]+)"')
"""Regex to extract Swift package names."""

_SWIFT_PACKAGE_URL_RE = re.compile(
    r'\.package\s*\(\s*url:\s*"[^"]*\/([^"\/]+?)(?:\.git)?"'
)
"""Regex to extract Swift package names from URL-based declarations."""

_MIX_DEP_RE = re.compile(r"\{:([a-zA-Z_][a-zA-Z0-9_]*)")
"""Regex to extract Elixir dependency atoms from mix.exs."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestInfo:
    """Parsed metadata from a single manifest file.

    Attributes:
        manifest_type: Identifier for the manifest file
            (e.g. ``"package.json"``, ``"Cargo.toml"``).
        project_name: Name field from the manifest, if present.
        description: Description field from the manifest, if present.
        dependencies: Union of runtime and dev dependency names.
        raw_dependencies: Runtime-only dependency names.
        raw_dev_dependencies: Dev-only dependency names.
        package_manager: Detected package manager string
            (e.g. ``"npm"``, ``"cargo"``, ``"pip"``).
    """

    manifest_type: str
    project_name: str | None
    description: str | None
    dependencies: frozenset[str]
    raw_dependencies: frozenset[str]
    raw_dev_dependencies: frozenset[str]
    package_manager: str


@dataclass(frozen=True)
class ProjectTypeResult:
    """Aggregated result of project type detection.

    Attributes:
        primary_manifest: The first manifest found in priority
            order.  Determines primary project classification.
        manifests: All manifests found in the project directory.
        project_name: Name from the primary manifest, if any.
        description: Description from the primary manifest, if any.
        all_dependencies: Union of all dependency names across
            every manifest.
        package_manager: Package manager from the primary
            manifest, or ``None`` if no manifests found.
    """

    primary_manifest: ManifestInfo | None
    manifests: list[ManifestInfo] = field(default_factory=list)
    project_name: str | None = None
    description: str | None = None
    all_dependencies: frozenset[str] = frozenset()
    package_manager: str | None = None


# ---------------------------------------------------------------------------
# Safe I/O helpers
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


def _safe_read_json(path: Path) -> dict | None:
    """Read and parse a JSON file, returning ``None`` on any error.

    Args:
        path: Absolute path to the JSON file.

    Returns:
        The parsed JSON object as a dict, or ``None`` if reading or
        parsing failed, or if the top-level value is not a dict.
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _safe_read_toml(path: Path) -> dict | None:
    """Read and parse a TOML file, returning ``None`` on any error.

    Args:
        path: Absolute path to the TOML file.

    Returns:
        The parsed TOML data as a dict, or ``None`` if reading or
        parsing failed.
    """
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (
        FileNotFoundError,
        PermissionError,
        OSError,
        tomllib.TOMLDecodeError,
    ):
        return None


def _strip_version(requirement: str) -> str | None:
    """Extract the bare package name from a requirement string.

    Handles PEP 508 version specifiers (``>=``, ``<``, ``~=``, etc.)
    as well as simple ``==`` pins.

    Args:
        requirement: A requirement string like ``"fastapi>=0.115,<1"``
            or ``"requests"``.

    Returns:
        The bare package name, or ``None`` if the string does not
        match the expected pattern.
    """
    requirement = requirement.strip()
    if not requirement:
        return None
    match = _PEP508_NAME_RE.match(requirement)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Private parsers
# ---------------------------------------------------------------------------


def _parse_package_json(
    manifest_path: Path, project_dir: Path
) -> ManifestInfo | None:
    """Parse ``package.json`` for project metadata and dependencies.

    Detects the package manager by checking for lockfiles in the
    project directory (``yarn.lock``, ``pnpm-lock.yaml``, ``bun.lockb``).

    Args:
        manifest_path: Path to the ``package.json`` file.
        project_dir: Root directory of the project.

    Returns:
        Parsed manifest info, or ``None`` on read/parse failure.
    """
    data = _safe_read_json(manifest_path)
    if data is None:
        return None

    name = data.get("name")
    description = data.get("description")
    runtime = frozenset(data.get("dependencies", {}).keys())
    dev = frozenset(data.get("devDependencies", {}).keys())

    # Detect package manager from lockfiles.
    if (project_dir / "yarn.lock").is_file():
        pm = "yarn"
    elif (project_dir / "pnpm-lock.yaml").is_file():
        pm = "pnpm"
    elif (project_dir / "bun.lockb").is_file():
        pm = "bun"
    else:
        pm = "npm"

    return ManifestInfo(
        manifest_type="package.json",
        project_name=name if isinstance(name, str) else None,
        description=description if isinstance(description, str) else None,
        dependencies=runtime | dev,
        raw_dependencies=runtime,
        raw_dev_dependencies=dev,
        package_manager=pm,
    )


def _parse_cargo_toml(
    manifest_path: Path, project_dir: Path
) -> ManifestInfo | None:
    """Parse ``Cargo.toml`` for project metadata and dependencies.

    Handles both single-package and workspace ``Cargo.toml`` files.
    For workspaces, ``[package]`` may be absent.

    Args:
        manifest_path: Path to the ``Cargo.toml`` file.
        project_dir: Root directory of the project.

    Returns:
        Parsed manifest info, or ``None`` on read/parse failure.
    """
    data = _safe_read_toml(manifest_path)
    if data is None:
        return None

    package = data.get("package", {})
    name = package.get("name")
    description = package.get("description")

    runtime = frozenset(data.get("dependencies", {}).keys())
    dev_deps = set(data.get("dev-dependencies", {}).keys())
    dev_deps.update(data.get("build-dependencies", {}).keys())
    dev = frozenset(dev_deps)

    return ManifestInfo(
        manifest_type="Cargo.toml",
        project_name=name if isinstance(name, str) else None,
        description=description if isinstance(description, str) else None,
        dependencies=runtime | dev,
        raw_dependencies=runtime,
        raw_dev_dependencies=dev,
        package_manager="cargo",
    )


def _parse_pyproject_toml(
    manifest_path: Path, project_dir: Path
) -> ManifestInfo | None:
    """Parse ``pyproject.toml`` for project metadata and dependencies.

    Supports both PEP 621 (``[project]``) and Poetry
    (``[tool.poetry]``) layouts.  Version specifiers are stripped from
    dependency strings.

    Args:
        manifest_path: Path to the ``pyproject.toml`` file.
        project_dir: Root directory of the project.

    Returns:
        Parsed manifest info, or ``None`` on read/parse failure.
    """
    data = _safe_read_toml(manifest_path)
    if data is None:
        return None

    project_section = data.get("project", {})
    name = project_section.get("name")
    description = project_section.get("description")

    # Poetry fallback for name/description.
    poetry = data.get("tool", {}).get("poetry", {})
    if not name:
        name = poetry.get("name")
    if not description:
        description = poetry.get("description")

    # PEP 621 dependencies.
    raw_deps_list = project_section.get("dependencies", [])
    runtime_names: set[str] = set()
    for dep_str in raw_deps_list:
        pkg_name = _strip_version(dep_str)
        if pkg_name:
            runtime_names.add(pkg_name)

    # PEP 621 optional-dependencies (treated as dev deps).
    optional_deps = project_section.get("optional-dependencies", {})
    dev_names: set[str] = set()
    for group_deps in optional_deps.values():
        for dep_str in group_deps:
            pkg_name = _strip_version(dep_str)
            if pkg_name:
                dev_names.add(pkg_name)

    # Poetry dependencies: [tool.poetry.dependencies].
    poetry_deps = poetry.get("dependencies", {})
    for dep_name in poetry_deps:
        if dep_name.lower() != "python":
            runtime_names.add(dep_name)

    # Poetry dev-dependencies (legacy section).
    poetry_dev_deps = poetry.get("dev-dependencies", {})
    for dep_name in poetry_dev_deps:
        dev_names.add(dep_name)

    # Poetry group dependencies.
    poetry_groups = poetry.get("group", {})
    for group_data in poetry_groups.values():
        group_dep_dict = group_data.get("dependencies", {})
        for dep_name in group_dep_dict:
            dev_names.add(dep_name)

    runtime = frozenset(runtime_names)
    dev = frozenset(dev_names)

    return ManifestInfo(
        manifest_type="pyproject.toml",
        project_name=name if isinstance(name, str) else None,
        description=description if isinstance(description, str) else None,
        dependencies=runtime | dev,
        raw_dependencies=runtime,
        raw_dev_dependencies=dev,
        package_manager="pip",
    )


def _parse_go_mod(
    manifest_path: Path, project_dir: Path
) -> ManifestInfo | None:
    """Parse ``go.mod`` for module name and dependencies.

    Extracts the module path and all required module paths from both
    block-style (``require ( ... )``) and single-line (``require ...``)
    directives.

    Args:
        manifest_path: Path to the ``go.mod`` file.
        project_dir: Root directory of the project.

    Returns:
        Parsed manifest info, or ``None`` on read/parse failure.
    """
    text = _safe_read_text(manifest_path)
    if text is None:
        return None

    # Module name from first "module" directive.
    module_match = _GO_MODULE_RE.search(text)
    module_name = module_match.group(1).strip() if module_match else None

    # Collect dependencies from require blocks.
    dep_paths: set[str] = set()
    for block_match in _GO_REQUIRE_BLOCK_RE.finditer(text):
        block_content = block_match.group(1)
        for line in block_content.splitlines():
            line = line.strip()
            if line and not line.startswith("//"):
                parts = line.split()
                if parts:
                    dep_paths.add(parts[0])

    # Collect dependencies from single-line require directives.
    for single_match in _GO_SINGLE_REQUIRE_RE.finditer(text):
        dep_paths.add(single_match.group(1))

    runtime = frozenset(dep_paths)

    return ManifestInfo(
        manifest_type="go.mod",
        project_name=module_name,
        description=None,
        dependencies=runtime,
        raw_dependencies=runtime,
        raw_dev_dependencies=frozenset(),
        package_manager="go",
    )


def _parse_requirements_txt(
    manifest_path: Path, project_dir: Path
) -> ManifestInfo | None:
    """Parse ``requirements.txt`` for dependency names.

    Skips blank lines, comments, and file-reference lines (``-r``,
    ``-c``).  Version specifiers are stripped.

    Args:
        manifest_path: Path to the ``requirements.txt`` file.
        project_dir: Root directory of the project.

    Returns:
        Parsed manifest info, or ``None`` on read/parse failure.
    """
    text = _safe_read_text(manifest_path)
    if text is None:
        return None

    dep_names: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-r", "-c", "-e", "-f", "-i", "--")):
            continue
        if "://" in line:
            continue
        pkg_name = _strip_version(line)
        if pkg_name:
            dep_names.add(pkg_name)

    runtime = frozenset(dep_names)

    return ManifestInfo(
        manifest_type="requirements.txt",
        project_name=None,
        description=None,
        dependencies=runtime,
        raw_dependencies=runtime,
        raw_dev_dependencies=frozenset(),
        package_manager="pip",
    )


def _parse_composer_json(
    manifest_path: Path, project_dir: Path
) -> ManifestInfo | None:
    """Parse ``composer.json`` for project metadata and dependencies.

    Filters out the ``php`` requirement and extensions prefixed with
    ``ext-`` from the runtime dependencies.

    Args:
        manifest_path: Path to the ``composer.json`` file.
        project_dir: Root directory of the project.

    Returns:
        Parsed manifest info, or ``None`` on read/parse failure.
    """
    data = _safe_read_json(manifest_path)
    if data is None:
        return None

    name = data.get("name")
    description = data.get("description")

    require = data.get("require", {})
    runtime = frozenset(
        k
        for k in require
        if k != "php" and not k.startswith("ext-")
    )

    dev = frozenset(data.get("require-dev", {}).keys())

    return ManifestInfo(
        manifest_type="composer.json",
        project_name=name if isinstance(name, str) else None,
        description=description if isinstance(description, str) else None,
        dependencies=runtime | dev,
        raw_dependencies=runtime,
        raw_dev_dependencies=dev,
        package_manager="composer",
    )


def _parse_gemfile(
    manifest_path: Path, project_dir: Path
) -> ManifestInfo | None:
    """Parse ``Gemfile`` for gem dependency names.

    Uses regex to extract gem names from ``gem '...'`` declarations.
    All gems are treated as runtime dependencies since Gemfile does
    not structurally separate dev gems in an easily parseable way.

    Args:
        manifest_path: Path to the ``Gemfile``.
        project_dir: Root directory of the project.

    Returns:
        Parsed manifest info, or ``None`` on read/parse failure.
    """
    text = _safe_read_text(manifest_path)
    if text is None:
        return None

    gems = frozenset(_GEMFILE_GEM_RE.findall(text))

    return ManifestInfo(
        manifest_type="Gemfile",
        project_name=None,
        description=None,
        dependencies=gems,
        raw_dependencies=gems,
        raw_dev_dependencies=frozenset(),
        package_manager="bundler",
    )


def _parse_gradle(
    manifest_path: Path, project_dir: Path
) -> ManifestInfo | None:
    """Parse ``build.gradle`` or ``build.gradle.kts`` for dependencies.

    Extracts artifact names from dependency declarations such as
    ``implementation 'group:artifact:version'``.

    Args:
        manifest_path: Path to the Gradle build file.
        project_dir: Root directory of the project.

    Returns:
        Parsed manifest info, or ``None`` on read/parse failure.
    """
    text = _safe_read_text(manifest_path)
    if text is None:
        return None

    artifacts: set[str] = set()
    for match in _GRADLE_DEP_RE.finditer(text):
        coord = match.group(1)
        # coord is like "group:artifact" or "group:artifact:version".
        parts = coord.split(":")
        if len(parts) >= 2:
            artifacts.add(parts[1])

    runtime = frozenset(artifacts)

    return ManifestInfo(
        manifest_type=manifest_path.name,
        project_name=None,
        description=None,
        dependencies=runtime,
        raw_dependencies=runtime,
        raw_dev_dependencies=frozenset(),
        package_manager="gradle",
    )


def _parse_pom_xml(
    manifest_path: Path, project_dir: Path
) -> ManifestInfo | None:
    """Parse ``pom.xml`` for project metadata and dependencies.

    Handles the Maven XML namespace
    ``{http://maven.apache.org/POM/4.0.0}``.

    Args:
        manifest_path: Path to the ``pom.xml`` file.
        project_dir: Root directory of the project.

    Returns:
        Parsed manifest info, or ``None`` on read/parse failure.
    """
    text = _safe_read_text(manifest_path)
    if text is None:
        return None

    try:
        root = ET.fromstring(text)  # noqa: S314
    except ET.ParseError:
        return None

    # Detect Maven namespace.
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    def _find_text(element: ET.Element, tag: str) -> str | None:
        child = element.find(f"{ns}{tag}")
        return child.text if child is not None and child.text else None

    # Name: prefer <name>, fall back to <artifactId>.
    name = _find_text(root, "name") or _find_text(root, "artifactId")
    description = _find_text(root, "description")

    # Dependencies.
    artifact_ids: set[str] = set()
    for dep in root.iter(f"{ns}dependency"):
        aid = _find_text(dep, "artifactId")
        if aid:
            artifact_ids.add(aid)

    runtime = frozenset(artifact_ids)

    return ManifestInfo(
        manifest_type="pom.xml",
        project_name=name,
        description=description,
        dependencies=runtime,
        raw_dependencies=runtime,
        raw_dev_dependencies=frozenset(),
        package_manager="maven",
    )


def _parse_package_swift(
    manifest_path: Path, project_dir: Path
) -> ManifestInfo | None:
    """Parse ``Package.swift`` for package dependency names.

    Extracts package names from ``.package(name: "...")`` and
    ``.package(url: ".../PackageName.git")`` declarations.

    Args:
        manifest_path: Path to the ``Package.swift`` file.
        project_dir: Root directory of the project.

    Returns:
        Parsed manifest info, or ``None`` on read/parse failure.
    """
    text = _safe_read_text(manifest_path)
    if text is None:
        return None

    packages: set[str] = set()
    packages.update(_SWIFT_PACKAGE_NAME_RE.findall(text))
    packages.update(_SWIFT_PACKAGE_URL_RE.findall(text))

    runtime = frozenset(packages)

    return ManifestInfo(
        manifest_type="Package.swift",
        project_name=None,
        description=None,
        dependencies=runtime,
        raw_dependencies=runtime,
        raw_dev_dependencies=frozenset(),
        package_manager="swift",
    )


def _parse_mix_exs(
    manifest_path: Path, project_dir: Path
) -> ManifestInfo | None:
    """Parse ``mix.exs`` for Elixir dependency atoms.

    Extracts dependency names from ``{:dep_name, ...}`` patterns.

    Args:
        manifest_path: Path to the ``mix.exs`` file.
        project_dir: Root directory of the project.

    Returns:
        Parsed manifest info, or ``None`` on read/parse failure.
    """
    text = _safe_read_text(manifest_path)
    if text is None:
        return None

    deps = frozenset(_MIX_DEP_RE.findall(text))

    return ManifestInfo(
        manifest_type="mix.exs",
        project_name=None,
        description=None,
        dependencies=deps,
        raw_dependencies=deps,
        raw_dev_dependencies=frozenset(),
        package_manager="mix",
    )


def _parse_pubspec_yaml(
    manifest_path: Path, project_dir: Path
) -> ManifestInfo | None:
    """Parse ``pubspec.yaml`` for project metadata and dependencies.

    Uses a simple line-based indent parser to avoid requiring a PyYAML
    dependency.  Extracts ``name``, ``description``, and dependency
    keys under ``dependencies:`` and ``dev_dependencies:`` sections.

    Args:
        manifest_path: Path to the ``pubspec.yaml`` file.
        project_dir: Root directory of the project.

    Returns:
        Parsed manifest info, or ``None`` on read/parse failure.
    """
    text = _safe_read_text(manifest_path)
    if text is None:
        return None

    name: str | None = None
    description: str | None = None
    runtime_deps: set[str] = set()
    dev_deps: set[str] = set()

    current_section: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Root-level keys (no leading whitespace).
        if not line[0].isspace():
            if stripped.startswith("name:"):
                value = stripped[len("name:"):].strip()
                name = value.strip("'\"") if value else None
            elif stripped.startswith("description:"):
                value = stripped[len("description:"):].strip()
                description = value.strip("'\"") if value else None

            # Track which section we are in.
            if stripped == "dependencies:":
                current_section = "dependencies"
            elif stripped == "dev_dependencies:":
                current_section = "dev_dependencies"
            elif stripped.endswith(":"):
                # Any other root-level section resets the tracker.
                current_section = None
            elif ":" in stripped and not line[0].isspace():
                # Root-level key that is not a section header.
                current_section = None
            continue

        # Indented lines under a section.
        if current_section and line[0].isspace():
            # Skip deeply nested lines (only direct children).
            indent = len(line) - len(line.lstrip())
            if indent <= 4 and ":" in stripped:
                dep_name = stripped.split(":")[0].strip()
                if dep_name and not dep_name.startswith("#"):
                    if current_section == "dependencies":
                        runtime_deps.add(dep_name)
                    elif current_section == "dev_dependencies":
                        dev_deps.add(dep_name)

    runtime = frozenset(runtime_deps)
    dev = frozenset(dev_deps)

    return ManifestInfo(
        manifest_type="pubspec.yaml",
        project_name=name,
        description=description,
        dependencies=runtime | dev,
        raw_dependencies=runtime,
        raw_dev_dependencies=dev,
        package_manager="pub",
    )


# ---------------------------------------------------------------------------
# Parser dispatch table
# ---------------------------------------------------------------------------

_PARSERS: dict[str, Callable[[Path, Path], ManifestInfo | None]] = {
    "package.json": _parse_package_json,
    "Cargo.toml": _parse_cargo_toml,
    "pyproject.toml": _parse_pyproject_toml,
    "go.mod": _parse_go_mod,
    "requirements.txt": _parse_requirements_txt,
    "composer.json": _parse_composer_json,
    "Gemfile": _parse_gemfile,
    "build.gradle": _parse_gradle,
    "build.gradle.kts": _parse_gradle,
    "pom.xml": _parse_pom_xml,
    "Package.swift": _parse_package_swift,
    "mix.exs": _parse_mix_exs,
    "pubspec.yaml": _parse_pubspec_yaml,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_project_type(project_dir: Path) -> ProjectTypeResult:
    """Detect project type(s) by scanning for manifest files.

    Checks for all known manifest files in priority order.  The first
    manifest found determines primary classification, but ALL manifests
    are parsed for completeness.

    This function performs filesystem I/O (reading manifest files) but
    no database I/O.  It is safe to call from a thread pool executor.

    Args:
        project_dir: Resolved absolute path to the project directory.

    Returns:
        A ``ProjectTypeResult`` with parsed manifest data.  If no
        manifests are found, ``primary_manifest`` is ``None`` and
        ``manifests`` is empty.
    """
    manifests: list[ManifestInfo] = []

    for filename, _default_pm in MANIFEST_PRIORITY:
        manifest_path = project_dir / filename
        if not manifest_path.is_file():
            continue
        parser = _PARSERS.get(filename)
        if parser is None:
            continue
        try:
            result = parser(manifest_path, project_dir)
        except Exception:  # noqa: BLE001
            # Never crash the scanner because of a malformed manifest.
            continue
        if result is not None:
            manifests.append(result)

    if not manifests:
        return ProjectTypeResult(primary_manifest=None)

    primary = manifests[0]
    all_deps = frozenset().union(*(m.dependencies for m in manifests))

    return ProjectTypeResult(
        primary_manifest=primary,
        manifests=manifests,
        project_name=primary.project_name,
        description=primary.description,
        all_dependencies=all_deps,
        package_manager=primary.package_manager,
    )
