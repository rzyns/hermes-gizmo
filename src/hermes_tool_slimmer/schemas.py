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
            "mode": {"type": "string", "enum": ["eager", "keyword", "hybrid", "anthropic_tool_search"]},
        },
        "required": ["query"],
    },
}
