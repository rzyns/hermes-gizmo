from __future__ import annotations

import logging
from typing import Iterable

from .config import ToolSlimmerConfig
from .corpus import tool_name, tool_toolset
from .toolsets import is_mcp_schema
from .types import Schema

LOG = logging.getLogger(__name__)


def eligible_schemas(schemas: Iterable[Schema], cfg: ToolSlimmerConfig) -> list[Schema]:
    disabled = set(cfg.disabled_tools)
    disabled_toolsets = set(cfg.disabled_toolsets)
    out: list[Schema] = []
    for schema in schemas:
        if not isinstance(schema, dict):
            LOG.warning("skipping non-dict tool schema: type=%s", type(schema).__name__)
            continue
        name = tool_name(schema)
        toolset = tool_toolset(schema)
        if name in disabled or (toolset and toolset in disabled_toolsets):
            continue
        is_mcp = is_mcp_schema(schema)
        if is_mcp and not cfg.include_mcp_tools:
            continue
        if not is_mcp and not cfg.include_native_tools:
            continue
        out.append(schema)
    return out
