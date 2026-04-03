"""Tests for the project type detection module of the Engram scanning pipeline.

Validates manifest file parsing for all supported project types (package.json,
Cargo.toml, pyproject.toml, go.mod, requirements.txt, composer.json, Gemfile,
build.gradle, build.gradle.kts, pom.xml, Package.swift, mix.exs,
pubspec.yaml), the priority-based primary manifest selection, dependency
aggregation across multiple manifests, and resilience to malformed input files.

All tests use ``pytest``'s ``tmp_path`` fixture — no real project
directories are ever referenced.
"""

import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# sys.path setup — mirrors conftest.py convention
# ---------------------------------------------------------------------------
_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from scanner.analyzers.project_type import (  # noqa: E402
    MANIFEST_PRIORITY,
    ManifestInfo,
    ProjectTypeResult,
    detect_project_type,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_package_json(
    project_dir: Path,
    *,
    name: str = "test-project",
    description: str = "A test project",
    deps: dict[str, str] | None = None,
    dev_deps: dict[str, str] | None = None,
) -> None:
    """Write a ``package.json`` into *project_dir*."""
    data: dict = {"name": name, "description": description}
    if deps is not None:
        data["dependencies"] = deps
    if dev_deps is not None:
        data["devDependencies"] = dev_deps
    (project_dir / "package.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def _make_cargo_toml(
    project_dir: Path,
    *,
    name: str = "test-project",
    description: str = "A test project",
    deps: dict[str, str] | None = None,
    dev_deps: dict[str, str] | None = None,
    build_deps: dict[str, str] | None = None,
    workspace: bool = False,
) -> None:
    """Write a ``Cargo.toml`` into *project_dir*."""
    lines: list[str] = []
    if workspace:
        lines.append("[workspace]")
        lines.append('members = ["crate-a", "crate-b"]')
    else:
        lines.append("[package]")
        lines.append(f'name = "{name}"')
        lines.append(f'description = "{description}"')
        lines.append('version = "0.1.0"')
        lines.append('edition = "2021"')
    lines.append("")
    if deps:
        lines.append("[dependencies]")
        for k, v in deps.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    if dev_deps:
        lines.append("[dev-dependencies]")
        for k, v in dev_deps.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    if build_deps:
        lines.append("[build-dependencies]")
        for k, v in build_deps.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    (project_dir / "Cargo.toml").write_text("\n".join(lines), encoding="utf-8")


def _make_pyproject_toml(
    project_dir: Path,
    *,
    name: str = "test-project",
    description: str = "A test project",
    deps: list[str] | None = None,
    optional_deps: dict[str, list[str]] | None = None,
) -> None:
    """Write a PEP 621 ``pyproject.toml`` into *project_dir*.

    Note: pyproject deps are strings like ``"fastapi>=0.115,<1"``.
    """
    lines: list[str] = []
    lines.append("[project]")
    lines.append(f'name = "{name}"')
    lines.append(f'description = "{description}"')
    lines.append('version = "0.1.0"')
    if deps is not None:
        dep_strs = ", ".join(f'"{d}"' for d in deps)
        lines.append(f"dependencies = [{dep_strs}]")
    if optional_deps is not None:
        lines.append("")
        lines.append("[project.optional-dependencies]")
        for group, group_deps in optional_deps.items():
            dep_strs = ", ".join(f'"{d}"' for d in group_deps)
            lines.append(f"{group} = [{dep_strs}]")
    lines.append("")
    (project_dir / "pyproject.toml").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def _make_poetry_pyproject_toml(
    project_dir: Path,
    *,
    name: str = "test-project",
    description: str = "A test project",
    deps: dict[str, str] | None = None,
    dev_deps: dict[str, str] | None = None,
) -> None:
    """Write a Poetry-layout ``pyproject.toml`` into *project_dir*."""
    lines: list[str] = []
    lines.append("[tool.poetry]")
    lines.append(f'name = "{name}"')
    lines.append(f'description = "{description}"')
    lines.append('version = "0.1.0"')
    lines.append("")
    if deps is not None:
        lines.append("[tool.poetry.dependencies]")
        for k, v in deps.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    if dev_deps is not None:
        lines.append("[tool.poetry.dev-dependencies]")
        for k, v in dev_deps.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    (project_dir / "pyproject.toml").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def _make_go_mod(
    project_dir: Path,
    *,
    module: str = "example.com/test",
    deps: list[str] | None = None,
) -> None:
    """Write a ``go.mod`` into *project_dir*."""
    lines: list[str] = []
    lines.append(f"module {module}")
    lines.append("")
    lines.append("go 1.21")
    lines.append("")
    if deps:
        lines.append("require (")
        for d in deps:
            lines.append(f"\t{d}")
        lines.append(")")
    lines.append("")
    (project_dir / "go.mod").write_text("\n".join(lines), encoding="utf-8")


def _make_requirements_txt(
    project_dir: Path,
    *,
    deps: list[str] | None = None,
) -> None:
    """Write a ``requirements.txt`` into *project_dir*."""
    content = "\n".join(deps) if deps else ""
    (project_dir / "requirements.txt").write_text(content, encoding="utf-8")


def _make_composer_json(
    project_dir: Path,
    *,
    name: str = "vendor/test",
    description: str = "A test project",
    require: dict[str, str] | None = None,
    require_dev: dict[str, str] | None = None,
) -> None:
    """Write a ``composer.json`` into *project_dir*."""
    data: dict = {"name": name, "description": description}
    if require is not None:
        data["require"] = require
    if require_dev is not None:
        data["require-dev"] = require_dev
    (project_dir / "composer.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def _make_gemfile(
    project_dir: Path,
    *,
    gems: list[str] | None = None,
) -> None:
    """Write a ``Gemfile`` into *project_dir*."""
    lines: list[str] = ['source "https://rubygems.org"', ""]
    if gems:
        for g in gems:
            lines.append(f'gem "{g}"')
    (project_dir / "Gemfile").write_text("\n".join(lines), encoding="utf-8")


def _make_build_gradle(
    project_dir: Path,
    *,
    filename: str = "build.gradle",
    deps: list[str] | None = None,
) -> None:
    """Write a ``build.gradle`` or ``build.gradle.kts`` into *project_dir*.

    Each entry in *deps* should be a full dependency line like
    ``"implementation 'com.google.code.gson:gson:2.10.1'"``
    """
    lines: list[str] = ["plugins {", "    id 'java'", "}", ""]
    if deps:
        lines.append("dependencies {")
        for d in deps:
            lines.append(f"    {d}")
        lines.append("}")
    (project_dir / filename).write_text("\n".join(lines), encoding="utf-8")


def _make_pom_xml(
    project_dir: Path,
    *,
    artifact_id: str = "my-app",
    name: str | None = None,
    description: str | None = None,
    deps: list[tuple[str, str]] | None = None,
    use_namespace: bool = True,
) -> None:
    """Write a ``pom.xml`` into *project_dir*.

    Args:
        deps: List of (groupId, artifactId) tuples.
        use_namespace: Whether to include the Maven XML namespace.
    """
    ns = ' xmlns="http://maven.apache.org/POM/4.0.0"' if use_namespace else ""
    lines: list[str] = [
        '<?xml version="1.0"?>',
        f"<project{ns}>",
        f"    <artifactId>{artifact_id}</artifactId>",
    ]
    if name is not None:
        lines.append(f"    <name>{name}</name>")
    if description is not None:
        lines.append(f"    <description>{description}</description>")
    if deps:
        lines.append("    <dependencies>")
        for group_id, aid in deps:
            lines.append("        <dependency>")
            lines.append(f"            <groupId>{group_id}</groupId>")
            lines.append(f"            <artifactId>{aid}</artifactId>")
            lines.append("            <version>1.0.0</version>")
            lines.append("        </dependency>")
        lines.append("    </dependencies>")
    lines.append("</project>")
    (project_dir / "pom.xml").write_text("\n".join(lines), encoding="utf-8")


def _make_package_swift(
    project_dir: Path,
    *,
    named_packages: list[str] | None = None,
    url_packages: list[str] | None = None,
) -> None:
    """Write a ``Package.swift`` into *project_dir*.

    Args:
        named_packages: Package names added via ``.package(name: "...")``.
        url_packages: GitHub repo names added via ``.package(url: ".../Name.git")``.
    """
    lines: list[str] = [
        "// swift-tools-version:5.9",
        'import PackageDescription',
        "",
        "let package = Package(",
        '    name: "MyApp",',
        "    dependencies: [",
    ]
    for pkg in (named_packages or []):
        lines.append(
            f'        .package(name: "{pkg}", url: "https://github.com/org/{pkg}.git", from: "1.0.0"),'
        )
    for pkg in (url_packages or []):
        lines.append(
            f'        .package(url: "https://github.com/org/{pkg}.git", from: "1.0.0"),'
        )
    lines.append("    ]")
    lines.append(")")
    (project_dir / "Package.swift").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def _make_mix_exs(
    project_dir: Path,
    *,
    deps: list[str] | None = None,
) -> None:
    """Write a ``mix.exs`` into *project_dir*.

    Args:
        deps: List of Elixir atom names (e.g. ``["phoenix", "ecto_sql"]``).
    """
    lines: list[str] = [
        "defmodule MyApp.MixProject do",
        "  use Mix.Project",
        "",
    ]
    if deps is not None:
        lines.append("  defp deps do")
        lines.append("    [")
        for d in deps:
            lines.append(f'      {{:{d}, "~> 1.0.0"}},')
        lines.append("    ]")
        lines.append("  end")
    lines.append("end")
    (project_dir / "mix.exs").write_text("\n".join(lines), encoding="utf-8")


def _make_pubspec_yaml(
    project_dir: Path,
    *,
    name: str | None = None,
    description: str | None = None,
    deps: list[str] | None = None,
    dev_deps: list[str] | None = None,
) -> None:
    """Write a ``pubspec.yaml`` into *project_dir*."""
    lines: list[str] = []
    if name is not None:
        lines.append(f"name: {name}")
    if description is not None:
        lines.append(f"description: {description}")
    lines.append("")
    if deps is not None:
        lines.append("dependencies:")
        for d in deps:
            lines.append(f"  {d}: ^1.0.0")
        lines.append("")
    if dev_deps is not None:
        lines.append("dev_dependencies:")
        for d in dev_deps:
            lines.append(f"  {d}: ^1.0.0")
        lines.append("")
    (project_dir / "pubspec.yaml").write_text(
        "\n".join(lines), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# TestPackageJsonParsing
# ---------------------------------------------------------------------------


class TestPackageJsonParsing:
    """Tests for ``package.json`` parsing via ``detect_project_type``."""

    def test_extracts_name_and_description(self, tmp_path: Path) -> None:
        """Project name and description are extracted from package.json."""
        _make_package_json(tmp_path, name="my-app", description="My cool app")

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "package.json"
        assert result.project_name == "my-app"
        assert result.description == "My cool app"

    def test_extracts_runtime_dependencies(self, tmp_path: Path) -> None:
        """Runtime dependencies are extracted from the ``dependencies`` field."""
        _make_package_json(
            tmp_path,
            deps={"react": "^18.2.0", "react-dom": "^18.2.0"},
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"react", "react-dom"}
        )

    def test_extracts_dev_dependencies(self, tmp_path: Path) -> None:
        """Dev dependencies are extracted from the ``devDependencies`` field."""
        _make_package_json(
            tmp_path,
            dev_deps={"vitest": "^1.0.0", "typescript": "^5.0.0"},
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dev_dependencies == frozenset(
            {"vitest", "typescript"}
        )

    def test_combined_dependencies(self, tmp_path: Path) -> None:
        """``dependencies`` is the union of runtime and dev dependencies."""
        _make_package_json(
            tmp_path,
            deps={"react": "^18.0.0"},
            dev_deps={"vitest": "^1.0.0"},
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.dependencies == frozenset(
            {"react", "vitest"}
        )
        assert result.all_dependencies == frozenset({"react", "vitest"})

    def test_detects_yarn_from_lockfile(self, tmp_path: Path) -> None:
        """When ``yarn.lock`` is present, package_manager is ``'yarn'``."""
        _make_package_json(tmp_path)
        (tmp_path / "yarn.lock").write_text("# yarn lock", encoding="utf-8")

        result = detect_project_type(tmp_path)

        assert result.package_manager == "yarn"
        assert result.primary_manifest is not None
        assert result.primary_manifest.package_manager == "yarn"

    def test_detects_pnpm_from_lockfile(self, tmp_path: Path) -> None:
        """When ``pnpm-lock.yaml`` is present, package_manager is ``'pnpm'``."""
        _make_package_json(tmp_path)
        (tmp_path / "pnpm-lock.yaml").write_text(
            "lockfileVersion: 6.0", encoding="utf-8"
        )

        result = detect_project_type(tmp_path)

        assert result.package_manager == "pnpm"
        assert result.primary_manifest is not None
        assert result.primary_manifest.package_manager == "pnpm"

    def test_detects_bun_from_lockfile(self, tmp_path: Path) -> None:
        """When ``bun.lockb`` is present, package_manager is ``'bun'``."""
        _make_package_json(tmp_path)
        (tmp_path / "bun.lockb").write_bytes(b"\x00bun lock binary")

        result = detect_project_type(tmp_path)

        assert result.package_manager == "bun"
        assert result.primary_manifest is not None
        assert result.primary_manifest.package_manager == "bun"

    def test_defaults_to_npm(self, tmp_path: Path) -> None:
        """Without any lockfile, package_manager defaults to ``'npm'``."""
        _make_package_json(tmp_path)

        result = detect_project_type(tmp_path)

        assert result.package_manager == "npm"
        assert result.primary_manifest is not None
        assert result.primary_manifest.package_manager == "npm"

    def test_malformed_json_returns_empty_result(self, tmp_path: Path) -> None:
        """Invalid JSON causes the manifest to be skipped entirely."""
        (tmp_path / "package.json").write_text(
            "{ this is not valid json !!!", encoding="utf-8"
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is None
        assert result.manifests == []

    def test_missing_name_returns_none(self, tmp_path: Path) -> None:
        """When ``name`` is absent from package.json, ``project_name`` is None."""
        data = {"description": "no name here", "dependencies": {}}
        (tmp_path / "package.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.project_name is None
        assert result.description == "no name here"

    def test_empty_dependencies(self, tmp_path: Path) -> None:
        """Empty dependency objects produce empty frozensets."""
        _make_package_json(tmp_path, deps={}, dev_deps={})

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.dependencies == frozenset()
        assert result.primary_manifest.raw_dependencies == frozenset()
        assert result.primary_manifest.raw_dev_dependencies == frozenset()


# ---------------------------------------------------------------------------
# TestCargoTomlParsing
# ---------------------------------------------------------------------------


class TestCargoTomlParsing:
    """Tests for ``Cargo.toml`` parsing via ``detect_project_type``."""

    def test_extracts_name_and_description(self, tmp_path: Path) -> None:
        """Project name and description are extracted from ``[package]``."""
        _make_cargo_toml(tmp_path, name="engram-core", description="Core lib")

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "Cargo.toml"
        assert result.project_name == "engram-core"
        assert result.description == "Core lib"
        assert result.package_manager == "cargo"

    def test_extracts_dependencies(self, tmp_path: Path) -> None:
        """Runtime dependency names are extracted from ``[dependencies]``."""
        _make_cargo_toml(
            tmp_path,
            deps={"serde": "1.0", "tokio": "1.35"},
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"serde", "tokio"}
        )

    def test_extracts_dev_and_build_dependencies(self, tmp_path: Path) -> None:
        """Dev and build dependencies are both collected as dev deps."""
        _make_cargo_toml(
            tmp_path,
            deps={"serde": "1.0"},
            dev_deps={"criterion": "0.5"},
            build_deps={"cc": "1.0"},
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        # dev-dependencies and build-dependencies are both in raw_dev_dependencies.
        assert result.primary_manifest.raw_dev_dependencies == frozenset(
            {"criterion", "cc"}
        )
        # Combined dependencies includes all three.
        assert result.primary_manifest.dependencies == frozenset(
            {"serde", "criterion", "cc"}
        )

    def test_workspace_cargo_toml(self, tmp_path: Path) -> None:
        """A workspace Cargo.toml without ``[package]`` has name=None."""
        _make_cargo_toml(tmp_path, workspace=True)

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "Cargo.toml"
        assert result.project_name is None
        assert result.description is None

    def test_malformed_toml_returns_empty_result(self, tmp_path: Path) -> None:
        """Invalid TOML causes the manifest to be skipped."""
        (tmp_path / "Cargo.toml").write_text(
            "[package\nthis is broken toml !!!", encoding="utf-8"
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is None
        assert result.manifests == []

    def test_no_dependencies_section(self, tmp_path: Path) -> None:
        """A Cargo.toml with only ``[package]`` yields empty dependency sets."""
        _make_cargo_toml(tmp_path)

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.dependencies == frozenset()


# ---------------------------------------------------------------------------
# TestPyprojectTomlParsing
# ---------------------------------------------------------------------------


class TestPyprojectTomlParsing:
    """Tests for ``pyproject.toml`` parsing via ``detect_project_type``."""

    def test_extracts_name_and_description(self, tmp_path: Path) -> None:
        """PEP 621 name and description are extracted from ``[project]``."""
        _make_pyproject_toml(
            tmp_path, name="engram-sidecar", description="Backend API"
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "pyproject.toml"
        assert result.project_name == "engram-sidecar"
        assert result.description == "Backend API"
        assert result.package_manager == "pip"

    def test_extracts_dependencies_stripping_versions(
        self, tmp_path: Path
    ) -> None:
        """Version specifiers are stripped, leaving bare package names."""
        _make_pyproject_toml(
            tmp_path,
            deps=["fastapi>=0.115,<1", "uvicorn[standard]", "sqlmodel==0.0.16"],
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        # _strip_version extracts the bare name before version specifiers.
        # "uvicorn[standard]" -> PEP 508 regex matches "uvicorn".
        expected_deps = frozenset({"fastapi", "uvicorn", "sqlmodel"})
        assert result.primary_manifest.raw_dependencies == expected_deps

    def test_extracts_optional_dependencies_as_dev(
        self, tmp_path: Path
    ) -> None:
        """Optional dependencies are treated as dev dependencies."""
        _make_pyproject_toml(
            tmp_path,
            deps=["fastapi"],
            optional_deps={
                "dev": ["pytest>=7.0", "black"],
                "docs": ["sphinx"],
            },
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"fastapi"}
        )
        assert result.primary_manifest.raw_dev_dependencies == frozenset(
            {"pytest", "black", "sphinx"}
        )
        # Combined includes both runtime and dev.
        assert result.primary_manifest.dependencies == frozenset(
            {"fastapi", "pytest", "black", "sphinx"}
        )

    def test_poetry_layout(self, tmp_path: Path) -> None:
        """Poetry-style ``[tool.poetry]`` name, description, and deps are extracted."""
        _make_poetry_pyproject_toml(
            tmp_path,
            name="poetry-app",
            description="A Poetry project",
            deps={"python": "^3.12", "django": "^5.0", "celery": "^5.3"},
            dev_deps={"pytest": "^7.0"},
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.project_name == "poetry-app"
        assert result.description == "A Poetry project"
        # "python" is filtered out; "django" and "celery" are runtime.
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"django", "celery"}
        )
        assert result.primary_manifest.raw_dev_dependencies == frozenset(
            {"pytest"}
        )

    def test_malformed_toml_returns_empty_result(self, tmp_path: Path) -> None:
        """Invalid TOML causes the manifest to be skipped."""
        (tmp_path / "pyproject.toml").write_text(
            "[project\nbroken toml!!!", encoding="utf-8"
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is None
        assert result.manifests == []

    def test_empty_project_section(self, tmp_path: Path) -> None:
        """A pyproject.toml with an empty ``[project]`` yields no name or deps."""
        (tmp_path / "pyproject.toml").write_text(
            "[project]\n", encoding="utf-8"
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.project_name is None
        assert result.primary_manifest.dependencies == frozenset()


# ---------------------------------------------------------------------------
# TestGoModParsing
# ---------------------------------------------------------------------------


class TestGoModParsing:
    """Tests for ``go.mod`` parsing via ``detect_project_type``."""

    def test_extracts_module_name(self, tmp_path: Path) -> None:
        """The module path is extracted as the project name."""
        _make_go_mod(tmp_path, module="github.com/user/my-go-app")

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "go.mod"
        assert result.project_name == "github.com/user/my-go-app"
        assert result.package_manager == "go"

    def test_extracts_require_block_dependencies(
        self, tmp_path: Path
    ) -> None:
        """Dependencies in a ``require ( ... )`` block are extracted."""
        _make_go_mod(
            tmp_path,
            module="example.com/app",
            deps=[
                "github.com/gin-gonic/gin v1.9.1",
                "github.com/lib/pq v1.10.9",
            ],
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"github.com/gin-gonic/gin", "github.com/lib/pq"}
        )
        # go.mod has no dev deps.
        assert result.primary_manifest.raw_dev_dependencies == frozenset()

    def test_extracts_single_line_require(self, tmp_path: Path) -> None:
        """Single-line ``require`` directives are also parsed."""
        content = (
            "module example.com/app\n"
            "\n"
            "go 1.21\n"
            "\n"
            "require github.com/stretchr/testify v1.8.4\n"
        )
        (tmp_path / "go.mod").write_text(content, encoding="utf-8")

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert "github.com/stretchr/testify" in result.primary_manifest.dependencies

    def test_no_dependencies(self, tmp_path: Path) -> None:
        """A go.mod with no require directives yields empty dependency sets."""
        _make_go_mod(tmp_path, module="example.com/simple")

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.dependencies == frozenset()

    def test_description_is_always_none(self, tmp_path: Path) -> None:
        """go.mod provides no description field."""
        _make_go_mod(tmp_path)

        result = detect_project_type(tmp_path)

        assert result.description is None


# ---------------------------------------------------------------------------
# TestRequirementsTxtParsing
# ---------------------------------------------------------------------------


class TestRequirementsTxtParsing:
    """Tests for ``requirements.txt`` parsing via ``detect_project_type``."""

    def test_extracts_dependency_names(self, tmp_path: Path) -> None:
        """Simple dependency names are extracted."""
        _make_requirements_txt(
            tmp_path, deps=["requests", "flask", "sqlalchemy"]
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "requirements.txt"
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"requests", "flask", "sqlalchemy"}
        )
        assert result.package_manager == "pip"

    def test_skips_comments_and_blanks(self, tmp_path: Path) -> None:
        """Blank lines and comment lines are ignored."""
        _make_requirements_txt(
            tmp_path,
            deps=[
                "# This is a comment",
                "",
                "requests",
                "  # indented comment",
                "",
                "flask",
            ],
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"requests", "flask"}
        )

    def test_strips_version_specifiers(self, tmp_path: Path) -> None:
        """Version specifiers like ``>=2.28`` are stripped to get bare names."""
        _make_requirements_txt(
            tmp_path,
            deps=["requests>=2.28", "flask==3.0.0", "uvicorn~=0.24"],
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"requests", "flask", "uvicorn"}
        )

    def test_skips_file_references(self, tmp_path: Path) -> None:
        """Lines starting with ``-r`` or ``-c`` are skipped."""
        _make_requirements_txt(
            tmp_path,
            deps=[
                "requests",
                "-r base-requirements.txt",
                "-c constraints.txt",
                "flask",
            ],
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"requests", "flask"}
        )

    def test_project_name_is_none(self, tmp_path: Path) -> None:
        """requirements.txt provides no project name."""
        _make_requirements_txt(tmp_path, deps=["requests"])

        result = detect_project_type(tmp_path)

        assert result.project_name is None

    def test_empty_file_yields_empty_deps(self, tmp_path: Path) -> None:
        """An empty requirements.txt produces empty dependency sets."""
        _make_requirements_txt(tmp_path, deps=[])

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.dependencies == frozenset()


# ---------------------------------------------------------------------------
# TestComposerJsonParsing
# ---------------------------------------------------------------------------


class TestComposerJsonParsing:
    """Tests for ``composer.json`` parsing via ``detect_project_type``."""

    def test_extracts_name_and_description(self, tmp_path: Path) -> None:
        """Project name and description are extracted from composer.json."""
        _make_composer_json(
            tmp_path,
            name="vendor/my-package",
            description="A PHP library",
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "composer.json"
        assert result.project_name == "vendor/my-package"
        assert result.description == "A PHP library"
        assert result.package_manager == "composer"

    def test_extracts_require_and_require_dev(self, tmp_path: Path) -> None:
        """Runtime and dev dependencies are correctly separated."""
        _make_composer_json(
            tmp_path,
            require={"laravel/framework": "^11.0", "guzzlehttp/guzzle": "^7.0"},
            require_dev={"phpunit/phpunit": "^10.0"},
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"laravel/framework", "guzzlehttp/guzzle"}
        )
        assert result.primary_manifest.raw_dev_dependencies == frozenset(
            {"phpunit/phpunit"}
        )
        assert result.primary_manifest.dependencies == frozenset(
            {"laravel/framework", "guzzlehttp/guzzle", "phpunit/phpunit"}
        )

    def test_filters_php_and_extensions(self, tmp_path: Path) -> None:
        """The ``php`` requirement and ``ext-*`` entries are filtered out."""
        _make_composer_json(
            tmp_path,
            require={
                "php": ">=8.2",
                "ext-json": "*",
                "ext-mbstring": "*",
                "monolog/monolog": "^3.0",
            },
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        # Only the actual package remains.
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"monolog/monolog"}
        )
        # php and ext-* are excluded.
        assert "php" not in result.primary_manifest.raw_dependencies
        assert "ext-json" not in result.primary_manifest.raw_dependencies
        assert "ext-mbstring" not in result.primary_manifest.raw_dependencies

    def test_malformed_json_returns_empty_result(self, tmp_path: Path) -> None:
        """Invalid JSON causes the manifest to be skipped."""
        (tmp_path / "composer.json").write_text(
            "{ broken json }", encoding="utf-8"
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is None
        assert result.manifests == []


# ---------------------------------------------------------------------------
# TestGemfileParsing
# ---------------------------------------------------------------------------


class TestGemfileParsing:
    """Tests for ``Gemfile`` parsing via ``detect_project_type``."""

    def test_extracts_gem_dependencies(self, tmp_path: Path) -> None:
        """Gem names are extracted from ``gem '...'`` declarations."""
        _make_gemfile(tmp_path, gems=["rails", "pg", "puma"])

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "Gemfile"
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"rails", "pg", "puma"}
        )
        assert result.package_manager == "bundler"

    def test_no_name_or_description(self, tmp_path: Path) -> None:
        """Gemfile provides no project name or description."""
        _make_gemfile(tmp_path, gems=["rails"])

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.project_name is None
        assert result.description is None

    def test_empty_gemfile(self, tmp_path: Path) -> None:
        """An empty Gemfile produces empty dependency sets."""
        _make_gemfile(tmp_path, gems=[])

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.dependencies == frozenset()
        assert result.primary_manifest.raw_dependencies == frozenset()
        assert result.primary_manifest.raw_dev_dependencies == frozenset()


# ---------------------------------------------------------------------------
# TestGradleParsing
# ---------------------------------------------------------------------------


class TestGradleParsing:
    """Tests for ``build.gradle`` / ``build.gradle.kts`` parsing via ``detect_project_type``."""

    def test_extracts_artifact_names(self, tmp_path: Path) -> None:
        """Artifact names are extracted from ``group:artifact:version`` coordinates."""
        _make_build_gradle(
            tmp_path,
            deps=[
                "implementation 'com.google.code.gson:gson:2.10.1'",
                "testImplementation 'junit:junit:4.13.2'",
            ],
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "build.gradle"
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"gson", "junit"}
        )
        assert result.package_manager == "gradle"

    def test_handles_groovy_and_kotlin_dsl(self, tmp_path: Path) -> None:
        """Both single-quoted (Groovy) and double-quoted (Kotlin DSL) strings are parsed."""
        _make_build_gradle(
            tmp_path,
            filename="build.gradle.kts",
            deps=[
                'implementation "org.springframework:spring-core:5.3.0"',
                "api 'io.netty:netty-all:4.1.0'",
            ],
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "build.gradle.kts"
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"spring-core", "netty-all"}
        )

    def test_no_dependencies(self, tmp_path: Path) -> None:
        """A Gradle build file with no dependency declarations yields empty sets."""
        _make_build_gradle(tmp_path, deps=[])

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.dependencies == frozenset()
        assert result.primary_manifest.raw_dependencies == frozenset()


# ---------------------------------------------------------------------------
# TestPomXmlParsing
# ---------------------------------------------------------------------------


class TestPomXmlParsing:
    """Tests for ``pom.xml`` parsing via ``detect_project_type``."""

    def test_extracts_name_and_description(self, tmp_path: Path) -> None:
        """Name and description are extracted from ``<name>`` and ``<description>`` elements."""
        _make_pom_xml(
            tmp_path,
            artifact_id="my-app",
            name="My Application",
            description="A test app",
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "pom.xml"
        assert result.project_name == "My Application"
        assert result.description == "A test app"
        assert result.package_manager == "maven"

    def test_extracts_dependencies(self, tmp_path: Path) -> None:
        """Artifact IDs are extracted from ``<dependency>`` elements."""
        _make_pom_xml(
            tmp_path,
            deps=[
                ("org.springframework", "spring-core"),
                ("com.fasterxml.jackson.core", "jackson-databind"),
            ],
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"spring-core", "jackson-databind"}
        )

    def test_handles_maven_namespace(self, tmp_path: Path) -> None:
        """Parsing works correctly with the Maven XML namespace."""
        _make_pom_xml(
            tmp_path,
            name="Namespaced App",
            description="With xmlns",
            deps=[("org.example", "example-lib")],
            use_namespace=True,
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.project_name == "Namespaced App"
        assert result.description == "With xmlns"
        assert "example-lib" in result.primary_manifest.raw_dependencies

    def test_malformed_xml_returns_empty_result(self, tmp_path: Path) -> None:
        """Invalid XML causes the manifest to be skipped."""
        (tmp_path / "pom.xml").write_text(
            "<project><name>broken<</name>", encoding="utf-8"
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is None
        assert result.manifests == []


# ---------------------------------------------------------------------------
# TestPackageSwiftParsing
# ---------------------------------------------------------------------------


class TestPackageSwiftParsing:
    """Tests for ``Package.swift`` parsing via ``detect_project_type``."""

    def test_extracts_named_packages(self, tmp_path: Path) -> None:
        """Package names from ``.package(name: "...")`` are extracted."""
        _make_package_swift(
            tmp_path, named_packages=["Alamofire", "SnapKit"]
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "Package.swift"
        assert "Alamofire" in result.primary_manifest.raw_dependencies
        assert "SnapKit" in result.primary_manifest.raw_dependencies
        assert result.package_manager == "swift"

    def test_extracts_url_packages(self, tmp_path: Path) -> None:
        """Package names from ``.package(url: ".../Name.git")`` are extracted."""
        _make_package_swift(tmp_path, url_packages=["vapor", "swift-nio"])

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert "vapor" in result.primary_manifest.raw_dependencies
        assert "swift-nio" in result.primary_manifest.raw_dependencies

    def test_no_dependencies(self, tmp_path: Path) -> None:
        """A Package.swift with no package declarations yields empty sets."""
        _make_package_swift(tmp_path)

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.dependencies == frozenset()
        assert result.primary_manifest.raw_dependencies == frozenset()


# ---------------------------------------------------------------------------
# TestMixExsParsing
# ---------------------------------------------------------------------------


class TestMixExsParsing:
    """Tests for ``mix.exs`` parsing via ``detect_project_type``."""

    def test_extracts_dependency_atoms(self, tmp_path: Path) -> None:
        """Elixir atom names are extracted from ``{:dep_name, ...}`` patterns."""
        _make_mix_exs(tmp_path, deps=["phoenix", "ecto_sql", "postgrex"])

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "mix.exs"
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"phoenix", "ecto_sql", "postgrex"}
        )
        assert result.package_manager == "mix"

    def test_no_deps_function(self, tmp_path: Path) -> None:
        """A mix.exs without a deps function yields empty dependency sets."""
        content = (
            "defmodule MyApp.MixProject do\n"
            "  use Mix.Project\n"
            "end\n"
        )
        (tmp_path / "mix.exs").write_text(content, encoding="utf-8")

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.dependencies == frozenset()

    def test_skips_non_dep_atoms(self, tmp_path: Path) -> None:
        """Only ``{:name`` patterns are matched; other content is ignored."""
        content = (
            "defmodule MyApp.MixProject do\n"
            "  use Mix.Project\n"
            "\n"
            "  def project do\n"
            '    [app: :my_app, version: "0.1.0"]\n'
            "  end\n"
            "\n"
            "  defp deps do\n"
            "    [\n"
            '      {:phoenix, "~> 1.7.0"},\n'
            '      {:jason, "~> 1.4"}\n'
            "    ]\n"
            "  end\n"
            "end\n"
        )
        (tmp_path / "mix.exs").write_text(content, encoding="utf-8")

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"phoenix", "jason"}
        )
        # The regex only matches {:atom patterns, not bare :atom references.
        assert "my_app" not in result.primary_manifest.raw_dependencies


# ---------------------------------------------------------------------------
# TestPubspecYamlParsing
# ---------------------------------------------------------------------------


class TestPubspecYamlParsing:
    """Tests for ``pubspec.yaml`` parsing via ``detect_project_type``."""

    def test_extracts_name_and_description(self, tmp_path: Path) -> None:
        """Root-level ``name`` and ``description`` are extracted."""
        _make_pubspec_yaml(
            tmp_path, name="my_app", description="A Flutter app"
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "pubspec.yaml"
        assert result.project_name == "my_app"
        assert result.description == "A Flutter app"
        assert result.package_manager == "pub"

    def test_extracts_dependencies(self, tmp_path: Path) -> None:
        """Dependencies under ``dependencies:`` are extracted."""
        _make_pubspec_yaml(tmp_path, name="my_app", deps=["http", "provider"])

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dependencies == frozenset(
            {"http", "provider"}
        )

    def test_extracts_dev_dependencies(self, tmp_path: Path) -> None:
        """Dev dependencies under ``dev_dependencies:`` are extracted."""
        _make_pubspec_yaml(
            tmp_path,
            name="my_app",
            deps=["http"],
            dev_deps=["build_runner", "flutter_test"],
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.raw_dev_dependencies == frozenset(
            {"build_runner", "flutter_test"}
        )
        # Combined should include both runtime and dev.
        assert result.primary_manifest.dependencies == frozenset(
            {"http", "build_runner", "flutter_test"}
        )

    def test_empty_pubspec(self, tmp_path: Path) -> None:
        """An empty pubspec.yaml produces an empty result."""
        (tmp_path / "pubspec.yaml").write_text("", encoding="utf-8")

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.project_name is None
        assert result.primary_manifest.description is None
        assert result.primary_manifest.dependencies == frozenset()
        assert result.primary_manifest.raw_dependencies == frozenset()
        assert result.primary_manifest.raw_dev_dependencies == frozenset()


# ---------------------------------------------------------------------------
# TestDetectProjectType (integration-level)
# ---------------------------------------------------------------------------


class TestDetectProjectType:
    """Integration-level tests for the ``detect_project_type`` public API."""

    def test_empty_dir_returns_empty_result(self, tmp_path: Path) -> None:
        """A directory with no manifest files returns an empty result."""
        result = detect_project_type(tmp_path)

        assert result.primary_manifest is None
        assert result.manifests == []
        assert result.project_name is None
        assert result.description is None
        assert result.all_dependencies == frozenset()
        assert result.package_manager is None

    def test_single_manifest_detected(self, tmp_path: Path) -> None:
        """A single manifest is both the primary and the only manifest."""
        _make_package_json(
            tmp_path,
            name="solo-app",
            description="Lone manifest",
            deps={"express": "^4.0"},
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert len(result.manifests) == 1
        assert result.manifests[0] is result.primary_manifest
        assert result.project_name == "solo-app"
        assert result.all_dependencies == frozenset({"express"})

    def test_multi_manifest_project(self, tmp_path: Path) -> None:
        """When multiple manifests exist, the highest priority one is primary."""
        _make_package_json(
            tmp_path,
            name="frontend",
            description="React UI",
            deps={"react": "^18.0"},
        )
        _make_cargo_toml(
            tmp_path,
            name="backend",
            description="Rust server",
            deps={"actix-web": "4.0"},
        )

        result = detect_project_type(tmp_path)

        # package.json has higher priority than Cargo.toml.
        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "package.json"
        assert result.project_name == "frontend"
        assert len(result.manifests) == 2

        manifest_types = [m.manifest_type for m in result.manifests]
        assert "package.json" in manifest_types
        assert "Cargo.toml" in manifest_types

    def test_priority_order_respected(self, tmp_path: Path) -> None:
        """``package.json`` beats ``Cargo.toml`` beats ``pyproject.toml``."""
        _make_pyproject_toml(tmp_path, name="py-proj", description="Python")
        _make_cargo_toml(tmp_path, name="rs-proj", description="Rust")
        _make_package_json(tmp_path, name="js-proj", description="JavaScript")

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "package.json"
        assert result.project_name == "js-proj"
        assert len(result.manifests) == 3

        # Manifests should be in priority order.
        types_in_order = [m.manifest_type for m in result.manifests]
        assert types_in_order == ["package.json", "Cargo.toml", "pyproject.toml"]

    def test_priority_cargo_beats_pyproject(self, tmp_path: Path) -> None:
        """Without ``package.json``, ``Cargo.toml`` is primary over ``pyproject.toml``."""
        _make_pyproject_toml(tmp_path, name="py-proj")
        _make_cargo_toml(tmp_path, name="rs-proj")

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "Cargo.toml"
        assert result.project_name == "rs-proj"

    def test_all_dependencies_union(self, tmp_path: Path) -> None:
        """Dependencies from all manifests are merged into ``all_dependencies``."""
        _make_package_json(tmp_path, deps={"react": "^18.0", "axios": "^1.6"})
        _make_pyproject_toml(tmp_path, deps=["fastapi", "uvicorn"])

        result = detect_project_type(tmp_path)

        assert result.all_dependencies == frozenset(
            {"react", "axios", "fastapi", "uvicorn"}
        )

    def test_project_name_from_primary(self, tmp_path: Path) -> None:
        """Name and description come from the primary manifest, not others."""
        _make_package_json(
            tmp_path, name="primary-name", description="Primary desc"
        )
        _make_pyproject_toml(
            tmp_path, name="secondary-name", description="Secondary desc"
        )

        result = detect_project_type(tmp_path)

        assert result.project_name == "primary-name"
        assert result.description == "Primary desc"

    def test_malformed_primary_falls_through(self, tmp_path: Path) -> None:
        """A malformed higher-priority manifest is skipped; the next valid one is primary."""
        # Write invalid package.json but valid pyproject.toml.
        (tmp_path / "package.json").write_text(
            "not valid json!!!", encoding="utf-8"
        )
        _make_pyproject_toml(
            tmp_path, name="fallback-app", description="Still works"
        )

        result = detect_project_type(tmp_path)

        assert result.primary_manifest is not None
        assert result.primary_manifest.manifest_type == "pyproject.toml"
        assert result.project_name == "fallback-app"
        assert len(result.manifests) == 1

    def test_package_manager_from_primary(self, tmp_path: Path) -> None:
        """Package manager is taken from the primary manifest."""
        _make_cargo_toml(tmp_path, name="rust-app")
        _make_requirements_txt(tmp_path, deps=["flask"])

        result = detect_project_type(tmp_path)

        # Cargo.toml has higher priority than requirements.txt.
        assert result.package_manager == "cargo"

    def test_nonexistent_directory_returns_empty(self, tmp_path: Path) -> None:
        """A nonexistent directory returns an empty result (no crash)."""
        bogus = tmp_path / "does_not_exist"

        result = detect_project_type(bogus)

        assert result.primary_manifest is None
        assert result.manifests == []


# ---------------------------------------------------------------------------
# TestDataStructures
# ---------------------------------------------------------------------------


class TestDataStructures:
    """Tests for the frozen dataclass structures."""

    def test_manifest_info_is_frozen(self) -> None:
        """``ManifestInfo`` instances are immutable."""
        mi = ManifestInfo(
            manifest_type="package.json",
            project_name="test",
            description="desc",
            dependencies=frozenset({"a"}),
            raw_dependencies=frozenset({"a"}),
            raw_dev_dependencies=frozenset(),
            package_manager="npm",
        )
        with pytest.raises(AttributeError):
            mi.project_name = "other"  # type: ignore[misc]

    def test_project_type_result_is_frozen(self) -> None:
        """``ProjectTypeResult`` instances are immutable."""
        ptr = ProjectTypeResult(primary_manifest=None)
        with pytest.raises(AttributeError):
            ptr.primary_manifest = None  # type: ignore[misc]

    def test_manifest_info_fields_correct(self) -> None:
        """``ManifestInfo`` stores all fields correctly."""
        runtime = frozenset({"react", "react-dom"})
        dev = frozenset({"vitest"})
        mi = ManifestInfo(
            manifest_type="package.json",
            project_name="my-app",
            description="Cool app",
            dependencies=runtime | dev,
            raw_dependencies=runtime,
            raw_dev_dependencies=dev,
            package_manager="npm",
        )
        assert mi.manifest_type == "package.json"
        assert mi.project_name == "my-app"
        assert mi.description == "Cool app"
        assert mi.dependencies == frozenset({"react", "react-dom", "vitest"})
        assert mi.raw_dependencies == runtime
        assert mi.raw_dev_dependencies == dev
        assert mi.package_manager == "npm"

    def test_project_type_result_defaults(self) -> None:
        """``ProjectTypeResult`` has sensible defaults for an empty result."""
        ptr = ProjectTypeResult(primary_manifest=None)
        assert ptr.primary_manifest is None
        assert ptr.manifests == []
        assert ptr.project_name is None
        assert ptr.description is None
        assert ptr.all_dependencies == frozenset()
        assert ptr.package_manager is None


# ---------------------------------------------------------------------------
# TestManifestPriority
# ---------------------------------------------------------------------------


class TestManifestPriority:
    """Tests for the ``MANIFEST_PRIORITY`` constant."""

    def test_priority_list_is_not_empty(self) -> None:
        """The priority list contains at least the major manifest types."""
        assert len(MANIFEST_PRIORITY) > 0

    def test_package_json_is_first(self) -> None:
        """``package.json`` is the highest-priority manifest."""
        assert MANIFEST_PRIORITY[0][0] == "package.json"

    def test_all_entries_have_two_elements(self) -> None:
        """Each entry is a (filename, default_package_manager) pair."""
        for entry in MANIFEST_PRIORITY:
            assert len(entry) == 2
            assert isinstance(entry[0], str)
            assert isinstance(entry[1], str)

    @pytest.mark.parametrize(
        "manifest_name",
        [
            "package.json",
            "Cargo.toml",
            "pyproject.toml",
            "go.mod",
            "requirements.txt",
            "composer.json",
            "Gemfile",
            "build.gradle",
            "build.gradle.kts",
            "pom.xml",
            "Package.swift",
            "mix.exs",
            "pubspec.yaml",
        ],
    )
    def test_major_manifests_present(self, manifest_name: str) -> None:
        """All major manifest types are included in the priority list."""
        filenames = [entry[0] for entry in MANIFEST_PRIORITY]
        assert manifest_name in filenames
