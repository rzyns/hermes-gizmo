"""Canonical Hermes Gizmo Python namespace compatibility tests."""

from __future__ import annotations

import importlib
from pathlib import Path

import tomllib


def test_hermes_gizmo_import_reexports_legacy_register() -> None:
    """The canonical package import should expose the same plugin register callable."""
    canonical = importlib.import_module("hermes_gizmo")
    legacy = importlib.import_module("hermes_tool_slimmer")

    assert canonical.register is legacy.register
    assert canonical.__version__ == legacy.__version__


def test_hermes_gizmo_submodule_reexports_legacy_objects() -> None:
    """Representative canonical submodules should preserve object identity."""
    canonical_config = importlib.import_module("hermes_gizmo.config")
    legacy_config = importlib.import_module("hermes_tool_slimmer.config")
    canonical_tools = importlib.import_module("hermes_gizmo.tools")
    legacy_tools = importlib.import_module("hermes_tool_slimmer.tools")

    assert canonical_config.ToolSlimmerConfig is legacy_config.ToolSlimmerConfig
    assert canonical_tools.tool_slimmer_status is legacy_tools.tool_slimmer_status


def test_hermes_gizmo_namespace_covers_current_legacy_module_inventory() -> None:
    """Every current legacy module gets an importable canonical counterpart."""
    repo_root = Path(__file__).resolve().parents[1]
    legacy_root = repo_root / "src" / "hermes_tool_slimmer"
    module_names = sorted(path.stem for path in legacy_root.glob("*.py") if path.name != "__init__.py")

    assert module_names, "expected legacy module inventory fixture"
    missing = []
    for module_name in module_names:
        try:
            importlib.import_module(f"hermes_gizmo.{module_name}")
        except ModuleNotFoundError:
            missing.append(module_name)

    assert missing == []


def test_wheel_configuration_includes_canonical_and_legacy_namespaces() -> None:
    """Built wheels must carry both the new canonical namespace and legacy shim."""
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    packages = set(wheel["packages"])
    include = set(wheel.get("include", []))

    assert "src/hermes_gizmo" in packages
    assert "src/hermes_tool_slimmer" in packages
    assert "/src/hermes_gizmo" in include
    assert "/src/hermes_tool_slimmer" in include


def test_pyproject_declares_canonical_and_legacy_plugin_entrypoints_and_scripts() -> None:
    """Package metadata should expose canonical Gizmo names without dropping legacy names."""
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    plugin_entrypoints = pyproject["project"]["entry-points"]["hermes_agent.plugins"]
    scripts = pyproject["project"]["scripts"]

    assert plugin_entrypoints["tool-slimmer"] == "hermes_tool_slimmer"
    assert plugin_entrypoints["gizmo"] == "hermes_gizmo"
    assert scripts["hermes-tool-slimmer"] == "hermes_tool_slimmer.cli:main"
    assert scripts["hermes-gizmo"] == "hermes_gizmo.cli:main"


def test_register_is_idempotent_when_legacy_and_canonical_entrypoints_both_load() -> None:
    """Mixed old/new plugin enablement must not double-register tools or commands."""
    from unittest.mock import MagicMock

    from hermes_gizmo import register

    ctx = MagicMock()
    register(ctx)
    register(ctx)

    assert ctx.register_tool.call_count == 14
    assert ctx.register_command.call_count == 2
    assert ctx.register_cli_command.call_count == 2
