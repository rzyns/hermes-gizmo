from hermes_tool_slimmer.anthropic_tool_search import apply_defer_loading, tool_search_tool
from hermes_tool_slimmer.config import ToolSlimmerConfig
from hermes_tool_slimmer.index_store import IndexStore
from hermes_tool_slimmer.metrics import reduction_metrics, schema_bytes, summarize_decisions
from hermes_tool_slimmer.toolsets import schema_origin


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


def test_index_store_saves_last_live_schemas(tmp_path):
    store = IndexStore(tmp_path)
    schemas = [{"name": f"tool_{idx}", "description": "Read"} for idx in range(20)]
    payload = store.save_live_schemas(schemas, {"platform": "tui", "session_id": "session-1"})

    assert payload["total_tools"] == 20
    assert store.load_live_schemas() == schemas


def test_index_store_ignores_probe_live_schemas(tmp_path):
    store = IndexStore(tmp_path)
    schemas = [{"name": "read_file", "description": "Read"}]

    store.save_live_schemas(schemas, {"platform": "test"})

    assert store.load_live_schemas() == []
    assert store.load_live_schemas(min_total_tools=0, require_session=False) == schemas


def test_index_store_load_live_schemas_defaults_to_small_sessions(tmp_path):
    store = IndexStore(tmp_path)
    schemas = [{"name": "read_file", "description": "Read"}]

    store.save_live_schemas(schemas, {"session_id": "session-1"})

    assert store.load_live_schemas() == schemas


def test_index_store_rejects_live_schema_checksum_mismatch(tmp_path):
    store = IndexStore(tmp_path)
    schemas = [{"name": f"tool_{idx}", "description": "Read"} for idx in range(20)]
    store.save_live_schemas(schemas, {"session_id": "session-1"})
    payload = store.live_schemas_path.read_text().replace("tool_0", "edited_tool")
    store.live_schemas_path.write_text(payload)

    assert store.load_live_schemas() == []


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


def test_index_load_returns_none_for_corrupt_json(tmp_path):
    store = IndexStore(tmp_path)
    store.path.write_text("{not json")
    assert store.load() is None


def test_metrics_estimate_reduction():
    original = [{"name": "a", "description": "x" * 100}, {"name": "b", "description": "y" * 100}]
    selected = [original[0]]
    metrics = reduction_metrics("keyword", original, selected, ["a"])
    assert metrics["schema_bytes_after"] < metrics["schema_bytes_before"]
    assert metrics["estimated_reduction_percent"] > 0


def test_schema_bytes_tolerates_non_json_values():
    assert schema_bytes([{"fn": lambda: None}]) > 0


def test_summarize_decisions_tolerates_bad_metric_types(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    log = tmp_path / "tool-slimmer" / "decisions.jsonl"
    log.parent.mkdir()
    log.write_text(
        '{"metrics":{"schema_bytes_before":"bad","schema_bytes_after":"bad","approx_tokens_before":"bad","approx_tokens_after":"bad","selected_tools":"bad","total_tools":"bad","selection_ms":"bad","estimated_reduction_percent":"bad","selected":"not-list"},"context":{}}\n'
    )

    summary = summarize_decisions()
    assert summary["totals"]["events"] == 1
    assert summary["totals"]["schema_bytes_before"] == 0
    assert summary["averages"]["selection_ms"] == 0.0


def test_schema_origin_tolerates_null_function_wrapper():
    assert schema_origin({"function": None}) == "native"


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
