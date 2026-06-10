from __future__ import annotations

from .integration import maybe_register_selector_hook
from .schemas import (
    CLEAR_VISIBLE_SKILL_PINS_SCHEMA,
    HYDRATE_TOOLS_SCHEMA,
    LOADED_TOOLS_SCHEMA,
    REQUEST_FULL_SKILL_INDEX_SCHEMA,
    REQUEST_FULL_TOOLS_SCHEMA,
    SELECT_SCHEMA,
    SKILL_DETAILS_SCHEMA,
    SKILL_SEARCH_SCHEMA,
    STATUS_SCHEMA,
    TOOL_DETAILS_SCHEMA,
    TOOL_SEARCH_SCHEMA,
    VISIBLE_SKILL_PINS_SCHEMA,
)
from .session_tools import (
    tool_slimmer_loaded_tools,
    tool_slimmer_tool_details,
    tool_slimmer_tool_search,
)
from .tools import tool_slimmer_hydrate_tools, tool_slimmer_request_full_tools, tool_slimmer_select, tool_slimmer_status

__all__ = ["register"]
__version__ = "0.7.0"


def register(ctx):
    """Register Hermes Gizmo plugin (formerly Tool Slimmer)."""
    marker = "_hermes_gizmo_registered"
    if getattr(ctx, marker, False) is True:
        return
    setattr(ctx, marker, True)

    from .cli import handle_cli, setup_argparse
    from .commands import handle_slash_command
    from .skills_tools import (
        tool_slimmer_clear_visible_skill_pins,
        tool_slimmer_request_full_skill_index,
        tool_slimmer_skill_details,
        tool_slimmer_skill_search,
        tool_slimmer_visible_skill_pins,
    )

    # Register tools under both old and new names
    ctx.register_tool(name="tool_slimmer_status", toolset="tool-slimmer", schema=STATUS_SCHEMA, handler=tool_slimmer_status)
    ctx.register_tool(name="gizmo_status", toolset="gizmo", schema=STATUS_SCHEMA, handler=tool_slimmer_status)
    ctx.register_tool(name="tool_slimmer_select", toolset="tool-slimmer", schema=SELECT_SCHEMA, handler=tool_slimmer_select)
    ctx.register_tool(name="gizmo_select", toolset="gizmo", schema=SELECT_SCHEMA, handler=tool_slimmer_select)
    ctx.register_tool(name="tool_slimmer_request_full_tools", toolset="tool-slimmer", schema=REQUEST_FULL_TOOLS_SCHEMA, handler=tool_slimmer_request_full_tools)
    ctx.register_tool(name="gizmo_request_full_tools", toolset="gizmo", schema=REQUEST_FULL_TOOLS_SCHEMA, handler=tool_slimmer_request_full_tools)
    ctx.register_tool(name="tool_slimmer_tool_search", toolset="tool-slimmer", schema=TOOL_SEARCH_SCHEMA, handler=tool_slimmer_tool_search)
    ctx.register_tool(name="gizmo_tool_search", toolset="gizmo", schema=TOOL_SEARCH_SCHEMA, handler=tool_slimmer_tool_search)
    ctx.register_tool(name="tool_slimmer_tool_details", toolset="tool-slimmer", schema=TOOL_DETAILS_SCHEMA, handler=tool_slimmer_tool_details)
    ctx.register_tool(name="gizmo_tool_details", toolset="gizmo", schema=TOOL_DETAILS_SCHEMA, handler=tool_slimmer_tool_details)
    ctx.register_tool(name="tool_slimmer_loaded_tools", toolset="tool-slimmer", schema=LOADED_TOOLS_SCHEMA, handler=tool_slimmer_loaded_tools)
    ctx.register_tool(name="gizmo_loaded_tools", toolset="gizmo", schema=LOADED_TOOLS_SCHEMA, handler=tool_slimmer_loaded_tools)
    ctx.register_tool(name="tool_slimmer_hydrate_tools", toolset="tool-slimmer", schema=HYDRATE_TOOLS_SCHEMA, handler=tool_slimmer_hydrate_tools)
    ctx.register_tool(name="gizmo_hydrate_tools", toolset="gizmo", schema=HYDRATE_TOOLS_SCHEMA, handler=tool_slimmer_hydrate_tools)
    ctx.register_tool(name="tool_slimmer_skill_search", toolset="tool-slimmer", schema=SKILL_SEARCH_SCHEMA, handler=tool_slimmer_skill_search)
    ctx.register_tool(name="gizmo_skill_search", toolset="gizmo", schema=SKILL_SEARCH_SCHEMA, handler=tool_slimmer_skill_search)
    ctx.register_tool(name="tool_slimmer_skill_details", toolset="tool-slimmer", schema=SKILL_DETAILS_SCHEMA, handler=tool_slimmer_skill_details)
    ctx.register_tool(name="gizmo_skill_details", toolset="gizmo", schema=SKILL_DETAILS_SCHEMA, handler=tool_slimmer_skill_details)
    ctx.register_tool(name="tool_slimmer_visible_skill_pins", toolset="tool-slimmer", schema=VISIBLE_SKILL_PINS_SCHEMA, handler=tool_slimmer_visible_skill_pins)
    ctx.register_tool(name="gizmo_visible_skill_pins", toolset="gizmo", schema=VISIBLE_SKILL_PINS_SCHEMA, handler=tool_slimmer_visible_skill_pins)
    ctx.register_tool(name="tool_slimmer_clear_visible_skill_pins", toolset="tool-slimmer", schema=CLEAR_VISIBLE_SKILL_PINS_SCHEMA, handler=tool_slimmer_clear_visible_skill_pins)
    ctx.register_tool(name="gizmo_clear_visible_skill_pins", toolset="gizmo", schema=CLEAR_VISIBLE_SKILL_PINS_SCHEMA, handler=tool_slimmer_clear_visible_skill_pins)
    ctx.register_tool(name="tool_slimmer_request_full_skill_index", toolset="tool-slimmer", schema=REQUEST_FULL_SKILL_INDEX_SCHEMA, handler=tool_slimmer_request_full_skill_index)
    ctx.register_tool(name="gizmo_request_full_skill_index", toolset="gizmo", schema=REQUEST_FULL_SKILL_INDEX_SCHEMA, handler=tool_slimmer_request_full_skill_index)

    # Register slash command under both names
    ctx.register_command("tool-slimmer", handler=handle_slash_command, description="Inspect and manage Hermes Gizmo")
    ctx.register_command("gizmo", handler=handle_slash_command, description="Inspect and manage Hermes Gizmo")

    # Register CLI command under both names
    ctx.register_cli_command(name="tool-slimmer", help="Inspect and manage Hermes Gizmo", setup_fn=setup_argparse, handler_fn=handle_cli)
    ctx.register_cli_command(name="gizmo", help="Inspect and manage Hermes Gizmo", setup_fn=setup_argparse, handler_fn=handle_cli)

    maybe_register_selector_hook(ctx)
