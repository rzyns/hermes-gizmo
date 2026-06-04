"""Test Hermes Gizmo soft-rename compatibility shims."""

from pathlib import Path

from hermes_tool_slimmer.config import ToolSlimmerConfig, load_config


class TestGizmoConfigAlias:
    """Config section alias: 'gizmo' key accepted alongside 'tool_slimmer'."""

    def test_load_config_accepts_gizmo_section(self, tmp_path: Path):
        config = tmp_path / "config.yaml"
        config.write_text(
            "gizmo:\n  mode: keyword\n  top_k: 4\n"
        )
        cfg = load_config(config)
        assert isinstance(cfg, ToolSlimmerConfig)
        assert cfg.mode == "keyword"
        assert cfg.top_k == 4

    def test_load_config_prefers_tool_slimmer_over_gizmo(self, tmp_path: Path):
        config = tmp_path / "config.yaml"
        config.write_text(
            "tool_slimmer:\n  mode: keyword\n  top_k: 8\n"
            "gizmo:\n  mode: two_pass\n  top_k: 4\n"
        )
        cfg = load_config(config)
        assert cfg.mode == "keyword"
        assert cfg.top_k == 8

    def test_load_config_falls_back_to_gizmo(self, tmp_path: Path):
        config = tmp_path / "config.yaml"
        config.write_text(
            "plugins:\n  enabled:\n    - gizmo\n"
            "gizmo:\n  mode: hybrid\n  top_k: 6\n"
        )
        cfg = load_config(config)
        assert cfg.mode == "hybrid"
        assert cfg.top_k == 6


class TestGizmoAliasRegistration:
    """Mock check that gizmo_* aliases are registered alongside originals."""

    def test_register_generates_dual_tools_and_commands(self):
        from unittest.mock import MagicMock

        ctx = MagicMock()
        from hermes_tool_slimmer import register

        register(ctx)

        tool_names = {r.kwargs["name"] for r in ctx.register_tool.call_args_list}
        old_tools = {
            "tool_slimmer_status",
            "tool_slimmer_select",
            "tool_slimmer_request_full_tools",
            "tool_slimmer_hydrate_tools",
            "tool_slimmer_loaded_tools",
            "tool_slimmer_tool_search",
            "tool_slimmer_tool_details",
        }
        new_tools = {
            "gizmo_status",
            "gizmo_select",
            "gizmo_request_full_tools",
            "gizmo_hydrate_tools",
            "gizmo_loaded_tools",
            "gizmo_tool_search",
            "gizmo_tool_details",
        }

        assert old_tools.issubset(tool_names), f"Missing old tools: {old_tools - tool_names}"
        assert new_tools.issubset(tool_names), f"Missing new tools: {new_tools - tool_names}"

        cmd_names = {r.args[0] for r in ctx.register_command.call_args_list}
        assert "tool-slimmer" in cmd_names
        assert "gizmo" in cmd_names

        cli_names = {r.kwargs["name"] for r in ctx.register_cli_command.call_args_list}
        assert "tool-slimmer" in cli_names
        assert "gizmo" in cli_names