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


def test_selector_always_includes_full_tools_request_when_available():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    schemas = [
        {"name": "tool_slimmer_request_full_tools", "toolset": "tool-slimmer", "description": "Request full tools"},
        {"name": "search_files", "toolset": "native", "description": "Search files in repo"},
        {"name": "terminal", "toolset": "native", "description": "Run shell commands"},
    ]
    result = ToolSelector(cfg).select("search files", schemas)
    assert result.selected_names == ["tool_slimmer_request_full_tools", "search_files"]
    assert result.always_included == ["tool_slimmer_request_full_tools"]
    assert "tool_slimmer_request_full_tools" not in result.scores


def test_selector_always_includes_progressive_discovery_tools_when_available():
    cfg = ToolSlimmerConfig(top_k=0, always_include=[])
    schemas = [
        {"name": "tool_slimmer_request_full_tools", "toolset": "tool-slimmer", "description": "Request full tools"},
        {"name": "tool_slimmer_tool_search", "toolset": "tool-slimmer", "description": "Search available tools"},
        {"name": "tool_slimmer_tool_details", "toolset": "tool-slimmer", "description": "Get tool details and load it"},
        {"name": "tool_slimmer_loaded_tools", "toolset": "tool-slimmer", "description": "List session-loaded tools"},
        {"name": "mcp_open_design_start_run", "toolset": "open-design", "description": "Start an Open Design run"},
    ]

    result = ToolSelector(cfg).select("create an Open Design artifact", schemas)

    assert result.selected_names == [
        "tool_slimmer_request_full_tools",
        "tool_slimmer_tool_search",
        "tool_slimmer_tool_details",
        "tool_slimmer_loaded_tools",
    ]
    assert result.always_included == result.selected_names
    assert not {"tool_slimmer_request_full_tools", "tool_slimmer_tool_search", "tool_slimmer_tool_details", "tool_slimmer_loaded_tools"} & set(result.scores)


def test_tool_slimmer_introspection_tools_do_not_compete_for_rank():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    schemas = [
        {"name": "tool_slimmer_select", "toolset": "tool-slimmer", "description": "Select relevant tools for a query"},
        {"name": "tool_slimmer_request_full_tools", "toolset": "tool-slimmer", "description": "Request full tools"},
        {"name": "execute_code", "description": "Query a database by running code"},
    ]
    result = ToolSelector(cfg).select("query a database", schemas)
    assert result.selected_names == ["tool_slimmer_request_full_tools", "execute_code"]
    assert "tool_slimmer_select" not in result.selected_names
    assert "tool_slimmer_select" not in result.scores


def test_hermes_native_bridge_tools_do_not_compete_for_rank():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    schemas = [
        {"name": "tool_search", "description": "Search available deferred tools"},
        {"name": "tool_describe", "description": "Describe a deferred tool"},
        {"name": "tool_call", "description": "Call a deferred tool"},
        {"name": "web_search", "description": "Search the web"},
    ]
    result = ToolSelector(cfg).select("search the web", schemas)
    assert result.selected_names == ["web_search"]
    assert "tool_search" not in result.scores


def test_selector_does_not_select_disabled_tools():
    cfg = ToolSlimmerConfig(top_k=5, always_include=[], disabled_toolsets=["github"])
    result = ToolSelector(cfg).select("github code search", SCHEMAS)
    assert "github_search_code" not in result.selected_names


def test_selector_skips_non_dict_schemas(caplog):
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    with caplog.at_level("WARNING", logger="hermes_tool_slimmer.selector"):
        result = ToolSelector(cfg).select("please use ok_tool", [{"name": "ok_tool", "description": "ok"}, None])
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


def test_cronjob_not_first_for_run_python_script():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    schemas = [
        {
            "name": "cronjob",
            "description": "Schedule recurring tasks with a script parameter",
            "parameters": {"properties": {"script": {"description": "Script to run"}}},
        },
        {"name": "execute_code", "description": "Run python scripts and execute code"},
    ]

    result = ToolSelector(cfg).select("run a python script", schemas)

    assert result.selected_names == ["execute_code"]
    assert result.score_details["cronjob"]["context_penalty"] < 0


def test_skill_manage_not_first_for_plain_file_edit():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    schemas = [
        {"name": "skill_manage", "description": "Manage skills with edit patch delete write_file actions"},
        {"name": "patch", "description": "Patch and edit repository files"},
        {"name": "write_file", "description": "Write or edit a file"},
    ]

    result = ToolSelector(cfg).select("edit this file", schemas)

    assert result.selected_names[0] in {"patch", "write_file"}
    assert result.score_details["skill_manage"]["context_penalty"] < 0


def test_skill_tools_are_kept_together_when_skill_context_selected():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    schemas = [
        {"name": "skill_manage", "description": "Manage skills and update procedural memory"},
        {"name": "skill_view", "description": "View a skill's full instructions"},
        {"name": "skills_list", "description": "List available skills"},
        {"name": "delegate_task", "description": "Delegate a task"},
    ]

    result = ToolSelector(cfg).select("update the skill for this workflow", schemas)

    assert "skill_manage" in result.selected_names
    assert "skill_view" in result.selected_names
    assert "skills_list" in result.selected_names


def test_recent_missing_tool_name_can_select_skill_view():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    schemas = [
        {"name": "skill_view", "description": "View a skill's full instructions"},
        {"name": "delegate_task", "description": "Delegate a task"},
    ]

    result = ToolSelector(cfg).select("12\n\nRecent missing/needed tool mentions: skill_view", schemas)

    assert result.selected_names == ["skill_view"]


def test_feishu_comment_tools_are_downranked_without_feishu_context():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    schemas = [
        {"name": "feishu_drive_list_comments", "description": "List Feishu drive comments"},
        {"name": "web_search", "description": "Search the web for GitHub PR comments"},
    ]

    result = ToolSelector(cfg).select("look up GitHub PR comments", schemas)

    assert result.selected_names == ["web_search"]
    assert result.score_details["feishu_drive_list_comments"]["context_penalty"] < 0


def test_feishu_edit_tools_are_downranked_for_file_edit_context():
    cfg = ToolSlimmerConfig(top_k=2, always_include=[])
    schemas = [
        {"name": "feishu_drive_add_comment", "description": "Add or edit Feishu drive comments"},
        {"name": "patch", "description": "Patch and edit repository files"},
        {"name": "write_file", "description": "Write or edit a file"},
    ]

    result = ToolSelector(cfg).select("edit this file", schemas)

    assert "feishu_drive_add_comment" not in result.selected_names
    assert result.score_details["feishu_drive_add_comment"]["context_penalty"] < 0


def test_feishu_tools_are_not_penalized_for_feishu_comment_context():
    cfg = ToolSlimmerConfig(top_k=1, always_include=[])
    schemas = [
        {"name": "feishu_drive_add_comment", "description": "Add Feishu drive comments"},
        {"name": "web_search", "description": "Search the web for comments"},
    ]

    result = ToolSelector(cfg).select("add a Feishu comment", schemas)

    assert result.selected_names == ["feishu_drive_add_comment"]
    assert result.score_details["feishu_drive_add_comment"]["context_penalty"] == 0


def test_browser_intent_downranks_cronjob_and_memory_noise():
    cfg = ToolSlimmerConfig(top_k=2, always_include=[])
    schemas = [
        {"name": "cronjob", "description": "Schedule skill tools and browser automation scripts"},
        {"name": "memory", "description": "Remember skill and tool context"},
        {"name": "browser_navigate", "description": "Navigate browser to a URL"},
        {"name": "browser_click", "description": "Click browser page elements"},
    ]

    result = ToolSelector(cfg).select("use a skill that needs browser tools", schemas)

    assert result.selected_names == ["browser_navigate", "browser_click"]
    assert result.score_details["cronjob"]["context_penalty"] < 0
    assert result.score_details["memory"]["context_penalty"] < 0


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


def test_weak_positive_matches_do_not_fill_top_k():
    cfg = ToolSlimmerConfig(top_k=3, always_include=["terminal"], min_score=99.0)
    result = ToolSelector(cfg).select("search", SCHEMAS)

    assert result.reason is None
    assert result.selected_names == ["terminal"]


def test_low_information_greeting_keeps_only_always_include_and_safety():
    cfg = ToolSlimmerConfig(top_k=4, always_include=["memory"])
    schemas = [
        {"name": "memory", "description": "Remember information"},
        {"name": "tool_slimmer_request_full_tools", "description": "Request full tools"},
        {"name": "terminal", "description": "Run shell commands"},
        {"name": "cronjob", "description": "Schedule recurring jobs"},
        {"name": "clarify", "description": "Ask a clarifying question"},
    ]

    result = ToolSelector(cfg).select("hello", schemas)

    assert result.reason == "low_information_query"
    assert result.selected_names == ["memory", "tool_slimmer_request_full_tools"]


def test_numeric_retry_keeps_only_always_include_and_safety_without_recent_mentions():
    cfg = ToolSlimmerConfig(top_k=4, always_include=["memory"])
    schemas = [
        {"name": "memory", "description": "Remember information"},
        {"name": "tool_slimmer_request_full_tools", "description": "Request full tools"},
        {"name": "terminal", "description": "Run shell commands"},
        {"name": "cronjob", "description": "Schedule recurring jobs"},
    ]

    result = ToolSelector(cfg).select("12", schemas)

    assert result.reason == "low_information_query"
    assert result.selected_names == ["memory", "tool_slimmer_request_full_tools"]


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
    assert result.scores["same"] == result.score_details["same"]["total"]


def test_selector_mode_kwarg_overrides_config():
    cfg = ToolSlimmerConfig(mode="keyword", top_k=1, always_include=[])
    schemas = [
        {"name": "repository_lookup", "description": "Find repository metadata"},
        {"name": "slack_send_message", "description": "Send Slack message"},
    ]
    result = ToolSelector(cfg).select("repozitory metadata", schemas, mode="hybrid")
    assert result.mode == "hybrid"
    assert result.selected_names == ["repository_lookup"]
    assert result.score_details["repository_lookup"]["hybrid_boost"] > 0


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
