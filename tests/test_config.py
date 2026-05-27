import pytest
import yaml

from hermes_tool_slimmer.config import ToolSlimmerConfig, load_config


def test_config_defaults():
    cfg = ToolSlimmerConfig.from_mapping({})
    assert cfg.enabled is True
    assert cfg.mode == "keyword"
    assert cfg.top_k == 8
    assert cfg.min_total_tools == 0


def test_config_full_mapping_and_nested_anthropic():
    cfg = ToolSlimmerConfig.from_mapping(
        {
            "enabled": False,
            "mode": "anthropic_tool_search",
            "top_k": 3,
            "disabled_tools": ["danger"],
            "anthropic": {
                "variant": "regex",
                "defer_native_tools": True,
                "tool_search_supported": True,
            },
            "aliases": {"repo": ["repository"]},
            "unknown": "ignored",
        }
    )
    assert cfg.enabled is False
    assert cfg.mode == "anthropic_tool_search"
    assert cfg.top_k == 3
    assert cfg.disabled_tools == ["danger"]
    assert cfg.anthropic.variant == "regex"
    assert cfg.anthropic.defer_native_tools is True
    assert cfg.anthropic.tool_search_supported is True
    assert cfg.aliases == {"repo": ["repository"]}


def test_config_ignores_invalid_anthropic_section_type():
    cfg = ToolSlimmerConfig.from_mapping({"anthropic": "tool_search"})
    assert cfg.anthropic.variant == "bm25"


def test_config_normalizes_string_list_shorthand():
    cfg = ToolSlimmerConfig.from_mapping(
        {
            "always_include": "terminal",
            "disabled_tools": ["danger", 123],
            "aliases": {"repo": "repository"},
            "anthropic": {"never_defer": "read_file"},
        }
    )

    assert cfg.always_include == ["terminal"]
    assert cfg.disabled_tools == ["danger", "123"]
    assert cfg.aliases == {"repo": ["repository"]}
    assert cfg.anthropic.never_defer == ["read_file"]


def test_config_accepts_always_exclude_alias():
    cfg = ToolSlimmerConfig.from_mapping({"always_exclude": ["terminal", "cronjob"]})

    assert cfg.disabled_tools == ["terminal", "cronjob"]
    assert cfg.always_exclude == ["terminal", "cronjob"]


def test_config_profiles_overlay_by_platform():
    cfg = ToolSlimmerConfig.from_mapping(
        {
            "top_k": 8,
            "always_include": ["terminal"],
            "profiles": {
                "telegram": {
                    "top_k": 4,
                    "always_include": ["memory"],
                    "always_exclude": ["cronjob"],
                },
                "tui": {"top_k": 9},
            },
        }
    )

    telegram = cfg.for_context(platform="telegram")
    cli = cfg.for_context(platform="tui")

    assert telegram.top_k == 4
    assert telegram.always_include == ["memory"]
    assert telegram.disabled_tools == ["cronjob"]
    assert cli.top_k == 9


def test_config_rejects_invalid_structured_types():
    with pytest.raises(ValueError, match="always_include"):
        ToolSlimmerConfig.from_mapping({"always_include": {"terminal": True}})
    with pytest.raises(ValueError, match="aliases"):
        ToolSlimmerConfig.from_mapping({"aliases": ["repo"]})
    with pytest.raises(ValueError, match="enabled"):
        ToolSlimmerConfig.from_mapping({"enabled": "yes"})
    with pytest.raises(ValueError, match="tool_search_supported"):
        ToolSlimmerConfig.from_mapping({"anthropic": {"tool_search_supported": "yes"}})


def test_config_invalid_mode():
    with pytest.raises(ValueError):
        ToolSlimmerConfig.from_mapping({"mode": "bad"})


def test_config_invalid_top_k():
    with pytest.raises(ValueError):
        ToolSlimmerConfig.from_mapping({"top_k": -1})


def test_config_rejects_nan_numeric_fields():
    with pytest.raises(ValueError, match="top_k"):
        ToolSlimmerConfig.from_mapping({"top_k": float("nan")})
    with pytest.raises(ValueError, match="min_estimated_reduction_percent"):
        ToolSlimmerConfig.from_mapping({"min_estimated_reduction_percent": float("nan")})


def test_load_config_reads_tool_slimmer_section(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"tool_slimmer": {"mode": "eager", "top_k": 0}}))
    cfg = load_config(path)
    assert cfg.mode == "eager"
    assert cfg.top_k == 0


def test_load_config_directory_path_returns_defaults(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.mode == "keyword"


def test_load_config_malformed_yaml_returns_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("  bad: yaml: here:\n  :invalid\n")

    cfg = load_config(path)

    assert cfg.mode == "keyword"
    assert cfg.min_total_tools == 0
