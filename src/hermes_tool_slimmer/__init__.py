from __future__ import annotations

from .integration import maybe_register_selector_hook
from .schemas import (
    HYDRATE_TOOLS_SCHEMA,
    LOADED_TOOLS_SCHEMA,
    REQUEST_FULL_TOOLS_SCHEMA,
    SELECT_SCHEMA,
    STATUS_SCHEMA,
    TOOL_DETAILS_SCHEMA,
    TOOL_SEARCH_SCHEMA,
)
from .session_tools import (
    tool_slimmer_loaded_tools,
    tool_slimmer_tool_details,
    tool_slimmer_tool_search,
)
from .tools import tool_slimmer_hydrate_tools, tool_slimmer_request_full_tools, tool_slimmer_select, tool_slimmer_status

__all__ = ["register"]
__version__ = "0.6.4"


def register(ctx):
    """Register Hermes Tool Slimmer plugin."""
    from .cli import handle_cli, setup_argparse
    from .commands import handle_slash_command

    ctx.register_tool(name="tool_slimmer_status", toolset="tool-slimmer", schema=STATUS_SCHEMA, handler=tool_slimmer_status)
    ctx.register_tool(name="tool_slimmer_select", toolset="tool-slimmer", schema=SELECT_SCHEMA, handler=tool_slimmer_select)
    ctx.register_tool(name="tool_slimmer_request_full_tools", toolset="tool-slimmer", schema=REQUEST_FULL_TOOLS_SCHEMA, handler=tool_slimmer_request_full_tools)
    ctx.register_tool(name="tool_slimmer_tool_search", toolset="tool-slimmer", schema=TOOL_SEARCH_SCHEMA, handler=tool_slimmer_tool_search)
    ctx.register_tool(name="tool_slimmer_tool_details", toolset="tool-slimmer", schema=TOOL_DETAILS_SCHEMA, handler=tool_slimmer_tool_details)
    ctx.register_tool(name="tool_slimmer_loaded_tools", toolset="tool-slimmer", schema=LOADED_TOOLS_SCHEMA, handler=tool_slimmer_loaded_tools)
    ctx.register_tool(name="tool_slimmer_hydrate_tools", toolset="tool-slimmer", schema=HYDRATE_TOOLS_SCHEMA, handler=tool_slimmer_hydrate_tools)
    ctx.register_command("tool-slimmer", handler=handle_slash_command, description="Inspect and manage Hermes Tool Slimmer")
    ctx.register_cli_command(name="tool-slimmer", help="Inspect and manage Hermes Tool Slimmer", setup_fn=setup_argparse, handler_fn=handle_cli)
    maybe_register_selector_hook(ctx)
