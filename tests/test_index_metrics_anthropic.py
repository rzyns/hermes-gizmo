from hermes_tool_slimmer.anthropic_tool_search import apply_defer_loading, tool_search_tool
from hermes_tool_slimmer.config import ToolSlimmerConfig
from hermes_tool_slimmer.index_store import IndexStore
from hermes_tool_slimmer.metrics import reduction_metrics


def test_index_rebuilds_on_schema_checksum_change(tmp_path):
    store = IndexStore(tmp_path)
    first = [{"name": "read_file", "description": "Read"}]
    second = [{"name": "read_file", "description": "Read files"}]
    one = store.ensure(first)
    two = store.ensure(second)
    assert one["checksum"] != two["checksum"]


def test_index_store_accepts_string_root(tmp_path):
    store = IndexStore(str(tmp_path / "index-root"))
    payload = store.rebuild([{"name": "read_file", "description": "Read"}])
    assert payload["total_tools"] == 1
    assert store.path.exists()


def test_index_checksum_tolerates_null_function_schema():
    checksum = IndexStore.checksum([{"name": None, "function": None}])
    assert isinstance(checksum, str)


def test_index_checksum_is_order_independent():
    schemas = [
        {"name": "read_file", "description": "Read"},
        {"name": "search_files", "description": "Search"},
        {"name": "terminal", "description": "Run commands"},
    ]

    assert IndexStore.checksum(schemas) == IndexStore.checksum(list(reversed(schemas)))


def test_metrics_estimate_reduction():
    original = [{"name": "a", "description": "x" * 100}, {"name": "b", "description": "y" * 100}]
    selected = [original[0]]
    metrics = reduction_metrics("keyword", original, selected, ["a"])
    assert metrics["schema_bytes_after"] < metrics["schema_bytes_before"]
    assert metrics["estimated_reduction_percent"] > 0


def test_anthropic_defer_never_defers_all_tools():
    cfg = ToolSlimmerConfig(mode="anthropic_tool_search")
    schemas = [{"name": "a", "toolset": "mcp"}, {"name": "b", "toolset": "mcp"}]
    transformed = apply_defer_loading(schemas, hot_tool_names=[], config=cfg)
    real_tools = [tool for tool in transformed if tool.get("name") != "tool_search_tool_bm25"]
    assert any(not tool.get("defer_loading") for tool in real_tools)
    assert transformed[0]["type"] == tool_search_tool()["type"]


def test_anthropic_provider_detection_excludes_openrouter_claude():
    from hermes_tool_slimmer.anthropic_tool_search import supports_anthropic_tool_search

    assert supports_anthropic_tool_search("anthropic", "claude-sonnet") is True
    assert supports_anthropic_tool_search("openrouter", "anthropic/claude-sonnet") is False
    assert supports_anthropic_tool_search("bedrock", "claude-sonnet") is False
    assert supports_anthropic_tool_search("bedrock", "claude-sonnet", True) is True


def test_anthropic_defer_treats_mcp_prefix_as_mcp():
    cfg = ToolSlimmerConfig(mode="anthropic_tool_search")
    schemas = [{"name": "hot"}, {"name": "issue_read", "toolset": "mcp:github"}]
    transformed = apply_defer_loading(schemas, hot_tool_names=["hot"], config=cfg)
    issue = next(tool for tool in transformed if tool.get("name") == "issue_read")
    assert issue["defer_loading"] is True


def test_anthropic_defer_treats_mcp_server_metadata_as_mcp():
    cfg = ToolSlimmerConfig(mode="anthropic_tool_search")
    schemas = [{"name": "hot"}, {"name": "issue_read", "mcp_server": "github"}]
    transformed = apply_defer_loading(schemas, hot_tool_names=["hot"], config=cfg)
    issue = next(tool for tool in transformed if tool.get("name") == "issue_read")
    assert issue["defer_loading"] is True
