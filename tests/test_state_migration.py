from __future__ import annotations

import json
from pathlib import Path

import yaml


def _snapshot_paths(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {path.relative_to(root) for path in root.rglob("*")}


def test_state_migration_plan_does_not_create_empty_roots(tmp_path):
    from hermes_tool_slimmer.state_migration import plan_state_migration

    config_path = tmp_path / "config.yaml"
    before = _snapshot_paths(tmp_path)

    report = plan_state_migration(hermes_home=tmp_path, config_path=config_path)

    assert report["ok"] is True
    assert report["effect"] == "dry_run"
    assert report["mutation_allowed"] is False
    assert report["legacy_root"]["path"] == str(tmp_path / "tool-slimmer")
    assert report["canonical_root"]["path"] == str(tmp_path / "gizmo")
    assert report["legacy_root"]["exists"] is False
    assert report["canonical_root"]["exists"] is False
    assert report["planned_actions"] == []
    assert _snapshot_paths(tmp_path) == before


def test_state_migration_plan_reports_legacy_state_and_config_actions_without_mutation(tmp_path):
    from hermes_tool_slimmer.state_migration import plan_state_migration

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "plugins": {"enabled": ["tool-slimmer"]},
                "tool_slimmer": {"enabled": True, "mode": "keyword", "top_k": 3},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    legacy_root = tmp_path / "tool-slimmer"
    legacy_root.mkdir()
    (legacy_root / "tool_index.json").write_text(json.dumps({"total_tools": 2}), encoding="utf-8")
    (legacy_root / "live_tool_schemas.json").write_text(json.dumps({"schemas": []}), encoding="utf-8")
    (legacy_root / "decisions.jsonl").write_text("{}\n", encoding="utf-8")
    (legacy_root / "session_loaded.json").write_text(json.dumps({"version": 2}), encoding="utf-8")
    (legacy_root / "semantic_cache").mkdir()
    (legacy_root / "semantic_cache" / "abc.json").write_text("{}", encoding="utf-8")
    before = _snapshot_paths(tmp_path)

    report = plan_state_migration(hermes_home=tmp_path, config_path=config_path)

    artifact_names = {item["name"] for item in report["artifacts"]}
    action_ids = {item["id"] for item in report["planned_actions"]}
    assert artifact_names == {
        "tool_index",
        "live_tool_schemas",
        "decisions_log",
        "session_loaded",
        "semantic_cache",
    }
    assert "copy_legacy_state_root" in action_ids
    assert "add_gizmo_config_section" in action_ids
    assert "enable_gizmo_plugin_alias" in action_ids
    assert report["config"]["sections"] == {"tool_slimmer": True, "gizmo": False}
    assert report["config"]["plugins_enabled"] == {"tool-slimmer": True, "gizmo": False}
    assert not (tmp_path / "gizmo").exists()
    assert _snapshot_paths(tmp_path) == before


def test_state_migration_plan_marks_existing_canonical_state_for_review(tmp_path):
    from hermes_tool_slimmer.state_migration import plan_state_migration

    legacy_root = tmp_path / "tool-slimmer"
    canonical_root = tmp_path / "gizmo"
    legacy_root.mkdir()
    canonical_root.mkdir()
    (legacy_root / "tool_index.json").write_text(json.dumps({"total_tools": 2}), encoding="utf-8")
    (canonical_root / "tool_index.json").write_text(json.dumps({"total_tools": 1}), encoding="utf-8")
    before = _snapshot_paths(tmp_path)

    report = plan_state_migration(hermes_home=tmp_path, config_path=tmp_path / "missing.yaml")

    assert report["canonical_root"]["exists"] is True
    assert any(warning["id"] == "canonical_state_exists" for warning in report["warnings"])
    copy_action = next(item for item in report["planned_actions"] if item["id"] == "copy_legacy_state_root")
    assert copy_action["requires_review"] is True
    assert copy_action["reason"] == "canonical_state_exists"
    assert _snapshot_paths(tmp_path) == before


def test_canonical_namespace_reexports_state_migration_planner(tmp_path):
    from hermes_gizmo.state_migration import plan_state_migration as canonical_plan
    from hermes_tool_slimmer.state_migration import plan_state_migration as legacy_plan

    assert canonical_plan is legacy_plan
    assert canonical_plan(hermes_home=tmp_path, config_path=tmp_path / "config.yaml")["effect"] == "dry_run"
