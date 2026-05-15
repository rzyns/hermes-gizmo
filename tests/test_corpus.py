from hermes_tool_slimmer.corpus import build_document, build_corpus, tool_description, tool_name


def test_tool_metadata_handles_null_function_wrapper():
    schema = {"name": None, "description": None, "function": None}

    assert tool_name(schema) == ""
    assert tool_description(schema) == ""
    assert build_corpus([schema]) == []


def test_tool_metadata_handles_valid_function_wrapper():
    schema = {"function": {"name": "wrapped_tool", "description": "Wrapped description"}}

    assert tool_name(schema) == "wrapped_tool"
    assert tool_description(schema) == "Wrapped description"


def test_build_document_handles_circular_parameter_schema():
    properties = {"query": {"description": "Search text"}}
    properties["self"] = properties
    schema = {"name": "circular", "parameters": {"properties": properties}}

    document = build_document(schema)

    assert document.name == "circular"
    assert "query" in document.tokens
    assert "search" in document.tokens
