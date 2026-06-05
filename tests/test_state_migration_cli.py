from __future__ import annotations

import json
from pathlib import Path

import yaml


def _paths(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {path.relative_to(root) for path in root.rglob("*")}


def test_cli_state_migration_plan_is_read_only_for_empty_home(monkeypatch, tmp_path, capsys):
    from hermes_tool_slimmer.cli import main

    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    before = _paths(tmp_path)

    assert main(["--config", str(config_path), "state-migration-plan"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["effect"] == "dry_run"
    assert payload["mutation_allowed"] is False
    assert payload["legacy_root"]["path"] == str(tmp_path / "tool-slimmer")
    assert payload["canonical_root"]["path"] == str(tmp_path / "gizmo")
    assert not (tmp_path / "tool-slimmer").exists()
    assert not (tmp_path / "gizmo").exists()
    assert _paths(tmp_path) == before


def test_cli_state_migration_plan_uses_config_argument_without_loading_config(monkeypatch, tmp_path, capsys):
    from hermes_tool_slimmer.cli import main

    config_path = tmp_path / "custom-config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "plugins": {"enabled": ["tool-slimmer"]},
                "tool_slimmer": {"enabled": True, "mode": "keyword"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    legacy_root = tmp_path / "tool-slimmer"
    legacy_root.mkdir()
    (legacy_root / "decisions.jsonl").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    before = _paths(tmp_path)

    assert main(["--config", str(config_path), "state-migration-plan"]) == 0

    payload = json.loads(capsys.readouterr().out)
    action_ids = {action["id"] for action in payload["planned_actions"]}
    assert payload["config"]["path"] == str(config_path)
    assert "copy_legacy_state_root" in action_ids
    assert "add_gizmo_config_section" in action_ids
    assert "enable_gizmo_plugin_alias" in action_ids
    assert {artifact["name"] for artifact in payload["artifacts"]} == {"decisions_log"}
    assert not (tmp_path / "gizmo").exists()
    assert _paths(tmp_path) == before


def test_canonical_cli_exposes_state_migration_plan(monkeypatch, tmp_path, capsys):
    from hermes_gizmo.cli import main

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    assert main(["--config", str(tmp_path / "config.yaml"), "state-migration-plan"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["effect"] == "dry_run"
