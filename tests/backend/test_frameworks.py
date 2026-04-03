"""Tests for the framework detection module of the Engram scanning pipeline.

Validates dependency-signal detection, file-presence detection, combined
detection with deduplication and sorting, and end-to-end integration
with the project type detection module.

All tests use ``pytest``'s ``tmp_path`` fixture for filesystem tests --
no real project directories are ever referenced.
"""

import json
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

from scanner.analyzers.frameworks import (  # noqa: E402
    DEPENDENCY_SIGNALS,
    FILE_SIGNALS,
    FrameworkDetectionResult,
    detect_frameworks,
)
from scanner.analyzers.project_type import (  # noqa: E402
    ManifestInfo,
    ProjectTypeResult,
    detect_project_type,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project_type_result(
    *,
    deps: frozenset[str] = frozenset(),
    dev_deps: frozenset[str] = frozenset(),
) -> ProjectTypeResult:
    """Build a minimal ``ProjectTypeResult`` for framework detection tests.

    The ``all_dependencies`` field receives ``deps | dev_deps``.

    Args:
        deps: Runtime dependency names.
        dev_deps: Dev-only dependency names.

    Returns:
        A ``ProjectTypeResult`` with the given dependencies wired through
        a synthetic ``ManifestInfo``.
    """
    if deps or dev_deps:
        manifest = ManifestInfo(
            manifest_type="test",
            project_name=None,
            description=None,
            dependencies=deps | dev_deps,
            raw_dependencies=deps,
            raw_dev_dependencies=dev_deps,
            package_manager="test",
        )
        return ProjectTypeResult(
            primary_manifest=manifest,
            manifests=[manifest],
            all_dependencies=deps | dev_deps,
        )
    return ProjectTypeResult(primary_manifest=None)


# ---------------------------------------------------------------------------
# TestDependencySignals
# ---------------------------------------------------------------------------


class TestDependencySignals:
    """Tests for dependency-based framework detection."""

    def test_detects_react(self, tmp_path: Path) -> None:
        """The ``react`` dependency triggers the ``react`` framework label."""
        ptr = _make_project_type_result(deps=frozenset({"react"}))
        result = detect_frameworks(tmp_path, ptr)

        assert "react" in result.frameworks

    def test_detects_react_from_react_dom(self, tmp_path: Path) -> None:
        """The ``react-dom`` dependency also triggers the ``react`` framework label."""
        ptr = _make_project_type_result(deps=frozenset({"react-dom"}))
        result = detect_frameworks(tmp_path, ptr)

        assert "react" in result.frameworks

    def test_detects_tauri(self, tmp_path: Path) -> None:
        """The ``@tauri-apps/api`` dependency triggers the ``tauri`` framework label."""
        ptr = _make_project_type_result(deps=frozenset({"@tauri-apps/api"}))
        result = detect_frameworks(tmp_path, ptr)

        assert "tauri" in result.frameworks

    def test_detects_tailwind_from_dev_deps(self, tmp_path: Path) -> None:
        """The ``tailwindcss`` dev dependency triggers ``tailwind-css``."""
        ptr = _make_project_type_result(dev_deps=frozenset({"tailwindcss"}))
        result = detect_frameworks(tmp_path, ptr)

        assert "tailwind-css" in result.frameworks

    def test_detects_fastapi(self, tmp_path: Path) -> None:
        """The ``fastapi`` dependency triggers the ``fastapi`` framework label."""
        ptr = _make_project_type_result(deps=frozenset({"fastapi"}))
        result = detect_frameworks(tmp_path, ptr)

        assert "fastapi" in result.frameworks

    def test_detects_django(self, tmp_path: Path) -> None:
        """The ``django`` dependency triggers the ``django`` framework label."""
        ptr = _make_project_type_result(deps=frozenset({"django"}))
        result = detect_frameworks(tmp_path, ptr)

        assert "django" in result.frameworks

    def test_detects_vue(self, tmp_path: Path) -> None:
        """The ``vue`` dependency triggers the ``vue`` framework label."""
        ptr = _make_project_type_result(deps=frozenset({"vue"}))
        result = detect_frameworks(tmp_path, ptr)

        assert "vue" in result.frameworks

    def test_detects_nextjs(self, tmp_path: Path) -> None:
        """The ``next`` dependency triggers the ``nextjs`` framework label."""
        ptr = _make_project_type_result(deps=frozenset({"next"}))
        result = detect_frameworks(tmp_path, ptr)

        assert "nextjs" in result.frameworks

    def test_detects_sqlmodel(self, tmp_path: Path) -> None:
        """The ``sqlmodel`` dependency triggers the ``sqlmodel`` framework label."""
        ptr = _make_project_type_result(deps=frozenset({"sqlmodel"}))
        result = detect_frameworks(tmp_path, ptr)

        assert "sqlmodel" in result.frameworks

    def test_detects_angular(self, tmp_path: Path) -> None:
        """The ``@angular/core`` dependency triggers the ``angular`` framework label."""
        ptr = _make_project_type_result(deps=frozenset({"@angular/core"}))
        result = detect_frameworks(tmp_path, ptr)

        assert "angular" in result.frameworks

    def test_no_deps_no_frameworks(self, tmp_path: Path) -> None:
        """Empty dependencies produce an empty frameworks list."""
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert result.frameworks == []

    def test_unknown_dep_ignored(self, tmp_path: Path) -> None:
        """Dependencies not in ``DEPENDENCY_SIGNALS`` are ignored."""
        ptr = _make_project_type_result(
            deps=frozenset({"some-obscure-lib", "my-private-package"})
        )
        result = detect_frameworks(tmp_path, ptr)

        assert result.frameworks == []

    def test_multiple_deps_detected(self, tmp_path: Path) -> None:
        """Multiple known dependencies each produce their framework label."""
        ptr = _make_project_type_result(
            deps=frozenset({"react", "express"}),
            dev_deps=frozenset({"tailwindcss"}),
        )
        result = detect_frameworks(tmp_path, ptr)

        assert "react" in result.frameworks
        assert "express" in result.frameworks
        assert "tailwind-css" in result.frameworks


# ---------------------------------------------------------------------------
# TestFileSignals
# ---------------------------------------------------------------------------


class TestFileSignals:
    """Tests for file-presence framework detection."""

    def test_detects_vite_config(self, tmp_path: Path) -> None:
        """A ``vite.config.ts`` file triggers the ``vite`` framework label."""
        (tmp_path / "vite.config.ts").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "vite" in result.frameworks

    def test_detects_vite_config_js(self, tmp_path: Path) -> None:
        """A ``vite.config.js`` file also triggers the ``vite`` framework label."""
        (tmp_path / "vite.config.js").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "vite" in result.frameworks

    def test_detects_tsconfig(self, tmp_path: Path) -> None:
        """A ``tsconfig.json`` file triggers the ``typescript`` framework label."""
        (tmp_path / "tsconfig.json").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "typescript" in result.frameworks

    def test_detects_github_actions(self, tmp_path: Path) -> None:
        """A ``.github/workflows/`` directory triggers ``github-actions``."""
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "github-actions" in result.frameworks

    def test_detects_dockerfile(self, tmp_path: Path) -> None:
        """A ``Dockerfile`` triggers the ``docker`` framework label."""
        (tmp_path / "Dockerfile").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "docker" in result.frameworks

    def test_detects_docker_compose_yml(self, tmp_path: Path) -> None:
        """A ``docker-compose.yml`` triggers the ``docker`` framework label."""
        (tmp_path / "docker-compose.yml").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "docker" in result.frameworks

    def test_detects_docker_compose_yaml(self, tmp_path: Path) -> None:
        """A ``docker-compose.yaml`` triggers the ``docker`` framework label."""
        (tmp_path / "docker-compose.yaml").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "docker" in result.frameworks

    def test_detects_dockerignore(self, tmp_path: Path) -> None:
        """A ``.dockerignore`` file triggers the ``docker`` framework label."""
        (tmp_path / ".dockerignore").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "docker" in result.frameworks

    def test_detects_eslint(self, tmp_path: Path) -> None:
        """An ``.eslintrc.json`` file triggers the ``eslint`` framework label."""
        (tmp_path / ".eslintrc.json").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "eslint" in result.frameworks

    def test_detects_eslint_flat_config(self, tmp_path: Path) -> None:
        """An ``eslint.config.js`` file triggers the ``eslint`` framework label."""
        (tmp_path / "eslint.config.js").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "eslint" in result.frameworks

    def test_detects_prettier(self, tmp_path: Path) -> None:
        """A ``.prettierrc`` file triggers the ``prettier`` framework label."""
        (tmp_path / ".prettierrc").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "prettier" in result.frameworks

    def test_detects_tailwind_config(self, tmp_path: Path) -> None:
        """A ``tailwind.config.ts`` file triggers ``tailwind-css``."""
        (tmp_path / "tailwind.config.ts").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "tailwind-css" in result.frameworks

    def test_detects_jest_config(self, tmp_path: Path) -> None:
        """A ``jest.config.ts`` file triggers the ``jest`` framework label."""
        (tmp_path / "jest.config.ts").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "jest" in result.frameworks

    def test_detects_vitest_config(self, tmp_path: Path) -> None:
        """A ``vitest.config.ts`` file triggers the ``vitest`` framework label."""
        (tmp_path / "vitest.config.ts").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "vitest" in result.frameworks

    def test_detects_storybook(self, tmp_path: Path) -> None:
        """A ``.storybook`` directory triggers the ``storybook`` framework label."""
        (tmp_path / ".storybook").mkdir()
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "storybook" in result.frameworks

    def test_detects_playwright(self, tmp_path: Path) -> None:
        """A ``playwright.config.ts`` file triggers ``playwright``."""
        (tmp_path / "playwright.config.ts").write_text("")
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert "playwright" in result.frameworks

    def test_no_config_files_no_frameworks(self, tmp_path: Path) -> None:
        """An empty directory with no dependencies produces no frameworks."""
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert result.frameworks == []


# ---------------------------------------------------------------------------
# TestCombinedDetection
# ---------------------------------------------------------------------------


class TestCombinedDetection:
    """Tests for combined dependency + file detection."""

    def test_combines_dep_and_file_signals(self, tmp_path: Path) -> None:
        """Dependency and file signals are merged into one result."""
        (tmp_path / "vite.config.ts").write_text("")
        (tmp_path / "tsconfig.json").write_text("")
        ptr = _make_project_type_result(deps=frozenset({"react"}))

        result = detect_frameworks(tmp_path, ptr)

        assert result.frameworks == ["react", "typescript", "vite"]

    def test_deduplicates_same_framework(self, tmp_path: Path) -> None:
        """A framework detected via both dep and file appears only once."""
        # tailwindcss in deps AND tailwind.config.ts on disk
        (tmp_path / "tailwind.config.ts").write_text("")
        ptr = _make_project_type_result(dev_deps=frozenset({"tailwindcss"}))

        result = detect_frameworks(tmp_path, ptr)

        assert result.frameworks.count("tailwind-css") == 1

    def test_sorted_output(self, tmp_path: Path) -> None:
        """Frameworks are returned in alphabetical order."""
        (tmp_path / "vite.config.ts").write_text("")
        (tmp_path / "tsconfig.json").write_text("")
        (tmp_path / ".eslintrc.json").write_text("")
        ptr = _make_project_type_result(
            deps=frozenset({"react"}),
            dev_deps=frozenset({"tailwindcss"}),
        )

        result = detect_frameworks(tmp_path, ptr)

        assert result.frameworks == sorted(result.frameworks)

    def test_empty_project(self, tmp_path: Path) -> None:
        """A project with no deps and no config files has empty frameworks."""
        ptr = _make_project_type_result()
        result = detect_frameworks(tmp_path, ptr)

        assert result.frameworks == []

    def test_multiple_docker_signals_deduplicate(self, tmp_path: Path) -> None:
        """Multiple Docker-related files produce a single ``docker`` entry."""
        (tmp_path / "Dockerfile").write_text("")
        (tmp_path / "docker-compose.yml").write_text("")
        (tmp_path / ".dockerignore").write_text("")
        ptr = _make_project_type_result()

        result = detect_frameworks(tmp_path, ptr)

        assert result.frameworks.count("docker") == 1

    def test_react_and_react_dom_deduplicate(self, tmp_path: Path) -> None:
        """Both ``react`` and ``react-dom`` in deps produce a single ``react`` entry."""
        ptr = _make_project_type_result(
            deps=frozenset({"react", "react-dom"})
        )
        result = detect_frameworks(tmp_path, ptr)

        assert result.frameworks.count("react") == 1

    def test_tauri_cli_and_api_deduplicate(self, tmp_path: Path) -> None:
        """Both ``@tauri-apps/api`` and ``@tauri-apps/cli`` produce a single ``tauri``."""
        ptr = _make_project_type_result(
            deps=frozenset({"@tauri-apps/api"}),
            dev_deps=frozenset({"@tauri-apps/cli"}),
        )
        result = detect_frameworks(tmp_path, ptr)

        assert result.frameworks.count("tauri") == 1


# ---------------------------------------------------------------------------
# TestFullProjectScan
# ---------------------------------------------------------------------------


class TestFullProjectScan:
    """End-to-end tests using ``detect_project_type`` then ``detect_frameworks``."""

    def test_react_tauri_project(self, tmp_path: Path) -> None:
        """A React + Tauri project with tooling configs detects all frameworks."""
        package_json = {
            "name": "engram",
            "version": "0.1.0",
            "dependencies": {
                "react": "^19.0.0",
                "react-dom": "^19.0.0",
                "@tauri-apps/api": "^2.0.0",
            },
            "devDependencies": {
                "tailwindcss": "^4.0.0",
                "typescript": "^5.0.0",
            },
        }
        (tmp_path / "package.json").write_text(json.dumps(package_json))
        (tmp_path / "vite.config.ts").write_text("")
        (tmp_path / "tsconfig.json").write_text("")
        (tmp_path / "tailwind.config.ts").write_text("")

        ptr = detect_project_type(tmp_path)
        result = detect_frameworks(tmp_path, ptr)

        for expected in ["react", "tailwind-css", "tauri", "typescript", "vite"]:
            assert expected in result.frameworks, (
                f"Expected '{expected}' in {result.frameworks}"
            )

    def test_python_fastapi_project(self, tmp_path: Path) -> None:
        """A Python FastAPI project with Docker detects relevant frameworks."""
        pyproject_toml = """\
[project]
name = "engram-sidecar"
version = "0.1.0"
dependencies = [
    "fastapi>=0.115,<1",
    "sqlmodel>=0.0.22",
    "uvicorn>=0.34",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]
"""
        (tmp_path / "pyproject.toml").write_text(pyproject_toml)
        (tmp_path / "Dockerfile").write_text("")

        ptr = detect_project_type(tmp_path)
        result = detect_frameworks(tmp_path, ptr)

        for expected in ["docker", "fastapi", "sqlmodel"]:
            assert expected in result.frameworks, (
                f"Expected '{expected}' in {result.frameworks}"
            )

    def test_rust_project_with_github_actions(self, tmp_path: Path) -> None:
        """A Rust project with GitHub Actions detects ``actix`` and ``github-actions``."""
        cargo_toml = """\
[package]
name = "my-server"
version = "0.1.0"
edition = "2021"

[dependencies]
actix-web = "4"
serde = { version = "1", features = ["derive"] }
"""
        (tmp_path / "Cargo.toml").write_text(cargo_toml)
        (tmp_path / ".github" / "workflows").mkdir(parents=True)

        ptr = detect_project_type(tmp_path)
        result = detect_frameworks(tmp_path, ptr)

        for expected in ["actix", "github-actions"]:
            assert expected in result.frameworks, (
                f"Expected '{expected}' in {result.frameworks}"
            )

    def test_go_project_with_gin(self, tmp_path: Path) -> None:
        """A Go project with ``gin-gonic/gin`` detects the ``gin`` framework."""
        go_mod = """\
module github.com/user/myapi

go 1.22

require (
    github.com/gin-gonic/gin v1.10.0
)
"""
        (tmp_path / "go.mod").write_text(go_mod)

        ptr = detect_project_type(tmp_path)
        result = detect_frameworks(tmp_path, ptr)

        assert "gin" in result.frameworks

    def test_no_manifests_falls_through(self, tmp_path: Path) -> None:
        """A directory with no manifests and no config files produces empty frameworks."""
        (tmp_path / "README.md").write_text("# hello")

        ptr = detect_project_type(tmp_path)
        result = detect_frameworks(tmp_path, ptr)

        assert result.frameworks == []


# ---------------------------------------------------------------------------
# TestDataStructures
# ---------------------------------------------------------------------------


class TestDataStructures:
    """Tests for the frozen dataclass structures."""

    def test_framework_detection_result_is_frozen(self) -> None:
        """``FrameworkDetectionResult`` instances are immutable."""
        fdr = FrameworkDetectionResult(frameworks=["react", "vite"])
        with pytest.raises(FrozenInstanceError):
            fdr.frameworks = ["changed"]  # type: ignore[misc]

    def test_framework_detection_result_repr(self) -> None:
        """``FrameworkDetectionResult`` has a readable repr."""
        fdr = FrameworkDetectionResult(frameworks=["docker", "fastapi"])
        assert "docker" in repr(fdr)
        assert "fastapi" in repr(fdr)


# ---------------------------------------------------------------------------
# TestSignalCompleteness
# ---------------------------------------------------------------------------


class TestSignalCompleteness:
    """Sanity checks on the signal constant tables themselves."""

    def test_dependency_signals_are_tuples_of_two_strings(self) -> None:
        """Every entry in ``DEPENDENCY_SIGNALS`` is a ``(str, str)`` tuple."""
        for entry in DEPENDENCY_SIGNALS:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            dep_name, framework_label = entry
            assert isinstance(dep_name, str)
            assert isinstance(framework_label, str)

    def test_file_signals_are_tuples_of_three_strings(self) -> None:
        """Every entry in ``FILE_SIGNALS`` is a ``(str, str, str)`` tuple."""
        for entry in FILE_SIGNALS:
            assert isinstance(entry, tuple)
            assert len(entry) == 3
            pattern, signal_type, framework_label = entry
            assert isinstance(pattern, str)
            assert signal_type in {"file", "dir", "glob"}
            assert isinstance(framework_label, str)

    def test_no_duplicate_dependency_entries(self) -> None:
        """``DEPENDENCY_SIGNALS`` has no exact duplicate entries."""
        assert len(DEPENDENCY_SIGNALS) == len(set(DEPENDENCY_SIGNALS))

    def test_no_duplicate_file_entries(self) -> None:
        """``FILE_SIGNALS`` has no exact duplicate entries."""
        assert len(FILE_SIGNALS) == len(set(FILE_SIGNALS))
