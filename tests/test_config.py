import pytest
import yaml

from hermes_tool_slimmer.config import ToolSlimmerConfig, load_config


def test_config_defaults():
    cfg = ToolSlimmerConfig.from_mapping({})
    assert cfg.enabled is True
    assert cfg.mode == "keyword"
    assert cfg.top_k == 8


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


def test_config_ignores_invalid_anthropic_section_type():
    cfg = ToolSlimmerConfig.from_mapping({"anthropic": "tool_search"})
    assert cfg.anthropic.variant == "bm25"


def test_config_invalid_mode():
    with pytest.raises(ValueError):
        ToolSlimmerConfig.from_mapping({"mode": "bad"})


def test_config_invalid_top_k():
    with pytest.raises(ValueError):
        ToolSlimmerConfig.from_mapping({"top_k": -1})


def test_load_config_reads_tool_slimmer_section(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"tool_slimmer": {"mode": "eager", "top_k": 0}}))
    cfg = load_config(path)
    assert cfg.mode == "eager"
    assert cfg.top_k == 0
