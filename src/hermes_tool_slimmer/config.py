from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


VALID_MODES = {"eager", "keyword", "hybrid", "anthropic_tool_search"}


@dataclass
class AnthropicConfig:
    variant: str = "bm25"
    defer_mcp_tools: bool = True
    defer_native_tools: bool = False
    tool_search_supported: bool | None = None
    never_defer: list[str] = field(default_factory=lambda: ["terminal", "read_file", "search_files"])


@dataclass
class ToolSlimmerConfig:
    enabled: bool = True
    mode: str = "keyword"
    top_k: int = 8
    always_include: list[str] = field(default_factory=lambda: ["terminal", "read_file", "write_file", "patch", "search_files"])
    never_defer: list[str] = field(default_factory=lambda: ["terminal", "read_file"])
    disabled_tools: list[str] = field(default_factory=list)
    disabled_toolsets: list[str] = field(default_factory=list)
    include_mcp_tools: bool = True
    include_native_tools: bool = True
    log_decisions: bool = True
    fail_open: bool = True
    dry_run: bool = False
    min_total_tools: int = 20
    min_estimated_reduction_percent: float = 5.0
    aliases: dict[str, list[str]] = field(default_factory=dict)
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "ToolSlimmerConfig":
        raw = dict(data or {})
        anthropic_raw = raw.pop("anthropic", {}) or {}
        if not isinstance(anthropic_raw, dict):
            anthropic_raw = {}
        cfg = cls(**{key: value for key, value in raw.items() if key in cls.__dataclass_fields__ and key != "anthropic"})
        cfg.anthropic = AnthropicConfig(**{key: value for key, value in anthropic_raw.items() if key in AnthropicConfig.__dataclass_fields__})
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.mode not in VALID_MODES:
            raise ValueError(f"Invalid tool_slimmer.mode {self.mode!r}; expected one of {sorted(VALID_MODES)}")
        if self.top_k < 0:
            raise ValueError("tool_slimmer.top_k must be >= 0")
        if self.min_total_tools < 0:
            raise ValueError("tool_slimmer.min_total_tools must be >= 0")
        if self.min_estimated_reduction_percent < 0:
            raise ValueError("tool_slimmer.min_estimated_reduction_percent must be >= 0")


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()


def config_path() -> Path:
    return Path(os.environ.get("HERMES_CONFIG", hermes_home() / "config.yaml")).expanduser()


def load_config(path: str | Path | None = None) -> ToolSlimmerConfig:
    target = Path(path).expanduser() if path else config_path()
    if not target.is_file():
        return ToolSlimmerConfig()
    data = yaml.safe_load(target.read_text()) or {}
    section = data.get("tool_slimmer", data if "mode" in data else {})
    return ToolSlimmerConfig.from_mapping(section)
