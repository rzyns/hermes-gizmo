from hermes_tool_slimmer.config import ToolSlimmerConfig
from hermes_tool_slimmer.selector import ToolSelector
import pytest


SCHEMAS = [
    {"name": "terminal", "toolset": "native", "description": "Run shell commands"},
    {"name": "read_file", "toolset": "native", "description": "Read a file"},
    {"name": "search_files", "toolset": "native", "description": "Search files in repo"},
    {"name": "github_search_code", "toolset": "github", "description": "Search GitHub code", "parameters": {"properties": {"query": {"description": "search query"}}}},
    {"name": "slack_send_message", "toolset": "slack", "description": "Send Slack message"},
]


def test_selector_always_includes_core_tools():
    cfg = ToolSlimmerConfig(top_k=3, always_include=["terminal", "read_file"])
    result = ToolSelector(cfg).select("github code search", SCHEMAS)
    assert result.selected_names[:2] == ["terminal", "read_file"]


def test_selector_respects_top_k_after_always_includes():
    cfg = ToolSlimmerConfig(top_k=2, always_include=["terminal"])
    result = ToolSelector(cfg).select("github code search", SCHEMAS)
    assert len(result.selected_names) == 3
    assert result.selected_names[0] == "terminal"


def test_selector_does_not_select_disabled_tools():
    cfg = ToolSlimmerConfig(top_k=5, always_include=[], disabled_toolsets=["github"])
    result = ToolSelector(cfg).select("github code search", SCHEMAS)
    assert "github_search_code" not in result.selected_names


def test_selector_skips_non_dict_schemas(caplog):
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    with caplog.at_level("WARNING", logger="hermes_tool_slimmer.selector"):
        result = ToolSelector(cfg).select("ok", [{"name": "ok_tool", "description": "ok"}, None])
    assert result.selected_names == ["ok_tool"]
    assert "skipping non-dict tool schema" in caplog.text


def test_selector_fails_open_on_index_error(monkeypatch):
    cfg = ToolSlimmerConfig(top_k=2, always_include=[])
    selector = ToolSelector(cfg)
    monkeypatch.setattr(selector, "_eligible", lambda schemas: (_ for _ in ()).throw(RuntimeError("boom")))
    result = selector.select("anything", SCHEMAS)
    assert result.fail_open is True
    assert result.selected == SCHEMAS


def test_exact_tool_name_boost_selects_named_tool():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    result = ToolSelector(cfg).select("please use github_search_code", SCHEMAS)
    assert result.selected_names == ["github_search_code"]


def test_single_character_tool_name_does_not_get_substring_boost():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    schemas = [
        {"name": "a", "description": "single letter"},
        {"name": "search_tool", "description": "Search things"},
    ]
    result = ToolSelector(cfg).select("search", schemas)
    assert result.selected_names == ["search_tool"]
    assert result.scores["a"] < result.scores["search_tool"]


def test_selector_respects_include_mcp_tools_flag():
    cfg = ToolSlimmerConfig(top_k=5, always_include=[], include_mcp_tools=False)
    schemas = [*SCHEMAS, {"name": "mcp_read_issue", "toolset": "mcp", "description": "Read MCP issue"}]
    result = ToolSelector(cfg).select("mcp issue", schemas)
    assert "mcp_read_issue" not in result.selected_names


def test_selector_respects_include_mcp_tools_for_mcp_server_metadata():
    cfg = ToolSlimmerConfig(top_k=5, always_include=[], include_mcp_tools=False)
    schemas = [*SCHEMAS, {"name": "issue_read", "mcp_server": "github", "description": "Read issue"}]
    result = ToolSelector(cfg).select("read github issue", schemas)
    assert "issue_read" not in result.selected_names


def test_selector_respects_include_mcp_tools_for_hermes_mcp_name_prefix():
    cfg = ToolSlimmerConfig(top_k=5, always_include=[], include_mcp_tools=False)
    schemas = [*SCHEMAS, {"name": "mcp_github_read_issue", "description": "Read issue"}]
    result = ToolSelector(cfg).select("read github issue", schemas)
    assert "mcp_github_read_issue" not in result.selected_names


def test_selector_respects_include_mcp_tools_for_plain_server_metadata():
    cfg = ToolSlimmerConfig(top_k=5, always_include=[], include_mcp_tools=False)
    schemas = [*SCHEMAS, {"name": "issue_read", "server": "github", "description": "Read issue"}]
    result = ToolSelector(cfg).select("read github issue", schemas)
    assert "issue_read" not in result.selected_names


def test_empty_query_fails_open_instead_of_arbitrary_tool():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    result = ToolSelector(cfg).select("", SCHEMAS)
    assert result.fail_open is True
    assert result.reason == "no_relevant_match"
    assert result.selected == SCHEMAS


def test_top_k_zero_does_not_fail_open_to_all_tools():
    cfg = ToolSlimmerConfig(top_k=0, always_include=[], fail_open=True)
    result = ToolSelector(cfg).select("search", SCHEMAS)
    assert result.fail_open is False
    assert result.selected_names == []


def test_no_match_keeps_always_include_only():
    cfg = ToolSlimmerConfig(top_k=3, always_include=["terminal"])
    result = ToolSelector(cfg).select("xyzqwerty12345 nonsense", SCHEMAS)
    assert result.fail_open is False
    assert result.reason == "no_relevant_match"
    assert result.selected_names == ["terminal"]


def test_repeated_query_tokens_are_deduplicated_before_scoring():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    schemas = [
        {
            "name": "terminal",
            "description": ("open " * 10) + ("shell command process " * 20),
        },
        {
            "name": "clarify",
            "description": "open",
        },
    ]
    result = ToolSelector(cfg).select("open " * 100, schemas)
    assert result.selected_names == ["terminal"]


def test_duplicate_names_warn_and_keep_first_schema(caplog):
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    schemas = [
        {"name": "same", "description": "first search target", "first": True},
        {"name": "same", "description": "second search target", "first": False},
    ]
    with caplog.at_level("WARNING", logger="hermes_tool_slimmer.selector"):
        result = ToolSelector(cfg).select("search target", schemas)
    assert "duplicate tool schema names" in caplog.text
    assert result.selected == [schemas[0]]


def test_selector_validates_direct_config_instances():
    with pytest.raises(ValueError, match="top_k"):
        ToolSelector(ToolSlimmerConfig(top_k=-1))


def test_keyword_synonyms_route_browse_to_browser_navigation():
    cfg = ToolSlimmerConfig(top_k=3, always_include=[])
    schemas = [
        {"name": "session_search", "description": "Search previous sessions"},
        {"name": "clarify", "description": "Ask the user a clarifying question"},
        {"name": "send_message", "description": "Send a chat message"},
        {"name": "browser_navigate", "description": "Navigate browser to a URL"},
    ]
    result = ToolSelector(cfg).select("browse to a website", schemas)
    assert "browser_navigate" in result.selected_names
    assert result.selected_names[0] == "browser_navigate"
    assert result.score_details["browser_navigate"]["alias_boost"] > 0


def test_configured_aliases_expand_keyword_matching():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[], aliases={"repo": ["github", "code"]})
    result = ToolSelector(cfg).select("repo search", SCHEMAS)
    assert result.selected_names == ["github_search_code"]
    assert "github" in result.expanded_query_tokens


def test_hybrid_mode_adds_fuzzy_token_boost():
    cfg = ToolSlimmerConfig(mode="hybrid", top_k=1, always_include=[])
    schemas = [
        {"name": "repository_lookup", "description": "Find repository metadata"},
        {"name": "slack_send_message", "description": "Send Slack message"},
    ]
    result = ToolSelector(cfg).select("repozitory metadata", schemas)
    assert result.selected_names == ["repository_lookup"]
    assert result.score_details["repository_lookup"]["hybrid_boost"] > 0
