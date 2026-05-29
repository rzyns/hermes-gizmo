STATUS_SCHEMA = {
    "name": "tool_slimmer_status",
    "description": "Return Hermes Tool Slimmer status and configuration.",
    "parameters": {"type": "object", "properties": {}},
}

SELECT_SCHEMA = {
    "name": "tool_slimmer_select",
    "description": "Select likely relevant tools for a query from provided tool schemas.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "schemas": {"type": "array", "items": {"type": "object"}},
            "mode": {"type": "string", "enum": ["eager", "keyword", "hybrid", "anthropic_tool_search", "semantic_hybrid"]},
        },
        "required": ["query"],
    },
}

REQUEST_FULL_TOOLS_SCHEMA = {
    "name": "tool_slimmer_request_full_tools",
    "description": (
        "Request the full Hermes tool schema set for the next model call when "
        "a required tool is missing from the trimmed tool list."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Short explanation of the missing tool or skill requirement.",
            }
        },
    },
}

TOOL_SEARCH_SCHEMA = {
    "name": "tool_slimmer_tool_search",
    "description": "Search available tools by query and return ranked, loadable results.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query to match against tool names, descriptions, and toolsets.",
            },
            "schemas": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Optional list of tool schemas to search. Defaults to live Hermes schemas or the last index.",
            },
        },
        "required": ["query"],
    },
}

TOOL_DETAILS_SCHEMA = {
    "name": "tool_slimmer_tool_details",
    "description": "Return detailed information about a specific tool by name. Optionally load or unload it from session state.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Tool name to look up.",
            },
            "load": {
                "type": "boolean",
                "description": "If true, load the tool into session-loaded state after returning details.",
            },
            "unload": {
                "type": "boolean",
                "description": "If true, unload the tool from session-loaded state.",
            },
            "schemas": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Optional list of tool schemas to search. Defaults to live Hermes schemas or the last index.",
            },
        },
        "required": ["name"],
    },
}

LOADED_TOOLS_SCHEMA = {
    "name": "tool_slimmer_loaded_tools",
    "description": "List currently session-loaded tools with metadata and expiry.",
    "parameters": {"type": "object", "properties": {}},
}
