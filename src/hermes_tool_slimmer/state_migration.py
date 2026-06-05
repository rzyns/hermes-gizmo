from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .config import config_path as default_config_path
from .config import hermes_home as default_hermes_home

LEGACY_STATE_DIR = "tool-slimmer"
CANONICAL_STATE_DIR = "gizmo"

_ARTIFACTS = (
    ("tool_index", "tool_index.json"),
    ("live_tool_schemas", "live_tool_schemas.json"),
    ("live_tool_schema_snapshots", "live_tool_schemas"),
    ("decisions_log", "decisions.jsonl"),
    ("session_loaded", "session_loaded.json"),
    ("semantic_cache", "semantic_cache"),
    ("backups", "backups"),
)


def plan_state_migration(
    *,
    hermes_home: Path | str | None = None,
    config_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return a read-only migration plan from Tool Slimmer state to Gizmo state.

    The planner intentionally performs no writes and does not instantiate stateful
    helpers such as ``IndexStore`` because those helpers create directories as a
    side effect. It is a review artifact for a later, separately approved apply
    path.
    """

    home = Path(hermes_home).expanduser() if hermes_home is not None else default_hermes_home()
    cfg_path = Path(config_path).expanduser() if config_path is not None else default_config_path()
    legacy_root = home / LEGACY_STATE_DIR
    canonical_root = home / CANONICAL_STATE_DIR

    config = _inspect_config(cfg_path)
    artifacts = _inspect_artifacts(legacy_root, canonical_root)
    warnings: list[dict[str, Any]] = []
    planned_actions: list[dict[str, Any]] = []

    if canonical_root.exists() and legacy_root.exists():
        warnings.append(
            {
                "id": "canonical_state_exists",
                "message": "Canonical Gizmo state already exists; copying legacy state requires review to avoid overwriting newer data.",
                "path": str(canonical_root),
            }
        )

    if legacy_root.exists():
        planned_actions.append(
            {
                "id": "copy_legacy_state_root",
                "kind": "copy_tree",
                "source": str(legacy_root),
                "destination": str(canonical_root),
                "requires_review": canonical_root.exists(),
                "reason": "canonical_state_exists" if canonical_root.exists() else "canonical_state_missing",
            }
        )

    if config["exists"]:
        if config["sections"]["tool_slimmer"] and not config["sections"]["gizmo"]:
            planned_actions.append(
                {
                    "id": "add_gizmo_config_section",
                    "kind": "config_alias",
                    "path": str(cfg_path),
                    "source_section": "tool_slimmer",
                    "destination_section": "gizmo",
                    "requires_review": False,
                }
            )
        if config["plugins_enabled"]["tool-slimmer"] and not config["plugins_enabled"]["gizmo"]:
            planned_actions.append(
                {
                    "id": "enable_gizmo_plugin_alias",
                    "kind": "config_list_append",
                    "path": str(cfg_path),
                    "section": "plugins.enabled",
                    "value": "gizmo",
                    "requires_review": False,
                }
            )

    return {
        "ok": True,
        "effect": "dry_run",
        "mutation_allowed": False,
        "legacy_root": _root_summary(legacy_root),
        "canonical_root": _root_summary(canonical_root),
        "config": config,
        "artifacts": artifacts,
        "warnings": warnings,
        "planned_actions": planned_actions,
    }


def _root_summary(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
    }


def _inspect_config(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "parse_ok": None,
        "sections": {"tool_slimmer": False, "gizmo": False},
        "plugins_enabled": {"tool-slimmer": False, "gizmo": False},
    }
    if not path.exists():
        return summary
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        summary["parse_ok"] = False
        summary["error"] = str(exc)
        return summary
    summary["parse_ok"] = isinstance(data, dict)
    if not isinstance(data, dict):
        return summary
    summary["sections"] = {
        "tool_slimmer": isinstance(data.get("tool_slimmer"), dict),
        "gizmo": isinstance(data.get("gizmo"), dict),
    }
    plugins = data.get("plugins")
    enabled = plugins.get("enabled") if isinstance(plugins, dict) else []
    if not isinstance(enabled, list):
        enabled = []
    enabled_names = {str(item) for item in enabled}
    summary["plugins_enabled"] = {
        "tool-slimmer": "tool-slimmer" in enabled_names,
        "gizmo": "gizmo" in enabled_names,
    }
    return summary


def _inspect_artifacts(legacy_root: Path, canonical_root: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for name, relative in _ARTIFACTS:
        legacy_path = legacy_root / relative
        canonical_path = canonical_root / relative
        if not legacy_path.exists() and not canonical_path.exists():
            continue
        artifacts.append(
            {
                "name": name,
                "relative_path": relative,
                "legacy": _path_summary(legacy_path),
                "canonical": _path_summary(canonical_path),
            }
        )
    return artifacts


def _path_summary(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "kind": "missing",
    }
    if not path.exists():
        return summary
    if path.is_dir():
        files = [child for child in path.rglob("*") if child.is_file()]
        summary.update(
            {
                "kind": "directory",
                "file_count": len(files),
                "total_bytes": sum(_safe_size(child) for child in files),
            }
        )
        return summary
    summary.update(
        {
            "kind": "file",
            "size_bytes": _safe_size(path),
            "sha256": _sha256(path),
        }
    )
    return summary


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def dumps_plan(plan: dict[str, Any]) -> str:
    """Serialize a migration plan for CLI/dashboard surfaces."""

    return json.dumps(plan, indent=2, sort_keys=True)
