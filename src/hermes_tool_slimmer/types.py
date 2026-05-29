from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


Schema = dict[str, Any]


@dataclass(frozen=True)
class ToolDocument:
    name: str
    schema: Schema
    text: str
    tokens: list[str]
    toolset: str | None = None
    parameter_tokens: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class SelectionResult:
    mode: str
    selected: list[Schema]
    selected_names: list[str]
    scores: dict[str, float]
    total_tools: int
    always_included: list[str]
    fail_open: bool = False
    reason: str | None = None
    score_details: dict[str, dict[str, float]] = field(default_factory=dict)
    expanded_query_tokens: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
