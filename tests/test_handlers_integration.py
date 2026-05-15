import json
import importlib.util
from pathlib import Path

import pytest

from hermes_tool_slimmer.commands import handle_slash_command
from hermes_tool_slimmer.config import ToolSlimmerConfig
from hermes_tool_slimmer.cli import _load_schemas, _tool_names
from hermes_tool_slimmer.integration import maybe_register_selector_hook, select_tool_schemas_callback
from hermes_tool_slimmer.metrics import read_decisions, summarize_decisions
from hermes_tool_slimmer.index_store import IndexStore
from hermes_tool_slimmer.tools import tool_slimmer_select, tool_slimmer_status


def test_plugin_handlers_return_json_strings(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    status = tool_slimmer_status({})
    select = tool_slimmer_select({"query": "read", "schemas": [{"name": "read_file", "description": "Read"}]})
    slash = handle_slash_command("select read", schemas=[{"name": "read_file", "description": "Read"}])
    assert json.loads(status)["ok"] is True
    assert json.loads(select)["ok"] is True
    assert json.loads(slash)["ok"] is True


def test_tool_slimmer_select_honors_mode_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    result = json.loads(
        tool_slimmer_select(
            {
                "query": "search",
                "mode": "eager",
                "schemas": [
                    {"name": "read_file", "description": "Read"},
                    {"name": "search_files", "description": "Search"},
                ],
            }
        )
    )

    assert result["ok"] is True
    assert result["mode"] == "eager"
    assert result["selected"] == ["read_file", "search_files"]


def test_tool_slimmer_select_falls_back_to_index_when_schemas_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    IndexStore().rebuild(
        [
            {"name": "execute_code", "description": "Run python scripts and execute code"},
            {"name": "image_generate", "description": "Generate images"},
        ]
    )

    result = json.loads(tool_slimmer_select({"query": "run a python script", "mode": "keyword"}))

    assert result["ok"] is True
    assert result["schema_source"] == "index"
    assert result["schema_count"] == 2
    assert result["selected"][0] == "execute_code"


def test_cli_tool_names_tolerates_null_function_wrapper():
    assert _tool_names([{"function": None}]) == {""}


def test_cli_load_schemas_handles_missing_path(tmp_path):
    assert _load_schemas(str(tmp_path / "missing.yaml")) == []


def test_cli_load_schemas_accepts_tool_index_documents(tmp_path):
    path = tmp_path / "tool_index.json"
    path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "name": "execute_code",
                        "toolset": "native",
                        "tokens": ["execute", "code"],
                        "text": "execute_code\nRun Python scripts",
                    }
                ]
            }
        )
    )

    assert _load_schemas(str(path)) == [
        {
            "name": "execute_code",
            "toolset": "native",
            "description": "execute_code\nRun Python scripts",
        }
    ]


def test_cli_analyze_config_and_eval(tmp_path, capsys):
    from argparse import Namespace
    from hermes_tool_slimmer.cli import handle_cli

    schemas = tmp_path / "schemas.yaml"
    prompts = tmp_path / "prompts.yaml"
    schemas.write_text("schemas:\n- name: search_files\n  description: Search files\n")
    prompts.write_text("prompts:\n- name: search\n  text: search files\n  expected_any: [search_files]\n")

    assert handle_cli(Namespace(command="eval", config=None, schemas=str(schemas), prompts=str(prompts))) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["hit_rate"] == 1.0
    assert handle_cli(Namespace(command="eval", config=None, schemas=str(schemas), prompts=str(prompts), markdown=True)) == 0
    assert "# Tool Slimmer Eval Report" in capsys.readouterr().out
    assert handle_cli(Namespace(command="analyze-config", config=None)) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert "recommendations" in out
    assert handle_cli(Namespace(command="privacy", config=None)) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["raw_prompts_logged"] is False
    assert "metrics" in out["event_fields"]


def test_integration_contract_returns_none_when_disabled():
    out = select_tool_schemas_callback("read", [], [{"name": "read_file"}], "model", "platform", config=ToolSlimmerConfig(enabled=False))
    assert out is None


def test_integration_contract_dry_run_preserves_original_behavior():
    out = select_tool_schemas_callback(
        "read",
        [],
        [{"name": "read_file"}],
        "model",
        "platform",
        config=ToolSlimmerConfig(dry_run=True, log_decisions=False),
    )
    assert out is None


def test_selector_records_decision_metrics(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    schemas = [
        {"name": "read_file", "description": "Read files"},
        {"name": "search_files", "description": "Search files"},
        {"name": "slack_send_message", "description": "Send slack message"},
    ]
    out = select_tool_schemas_callback(
        "search files",
        [],
        schemas,
        "model",
        "dashboard",
        provider="test-provider",
        session_id="session-1",
        config=ToolSlimmerConfig(top_k=1, always_include=[], min_total_tools=0),
    )
    assert out == [schemas[1]]

    events = read_decisions()
    assert len(events) == 1
    assert events[0]["context"]["provider"] == "test-provider"
    assert events[0]["metrics"]["selected"] == ["search_files"]
    assert events[0]["metrics"]["approx_tokens_saved"] > 0
    summary = summarize_decisions()
    assert summary["totals"]["events"] == 1
    assert summary["totals"]["approx_tokens_saved"] > 0
    assert summarize_decisions(require_session=True)["totals"]["events"] == 1


def test_summary_can_exclude_no_session_probe_events(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    schemas = [
        {"name": "read_file", "description": "Read files"},
        {"name": "search_files", "description": "Search files"},
    ]
    select_tool_schemas_callback(
        "read",
        [],
        schemas,
        "model",
        "test",
        config=ToolSlimmerConfig(top_k=1, always_include=[], min_total_tools=0),
    )
    select_tool_schemas_callback(
        "search",
        [],
        schemas,
        "model",
        "tui",
        session_id="session-1",
        config=ToolSlimmerConfig(top_k=1, always_include=[], min_total_tools=0),
    )

    all_events = summarize_decisions()
    session_events = summarize_decisions(require_session=True)
    assert all_events["totals"]["events"] == 2
    assert session_events["totals"]["events"] == 1
    assert session_events["ignored_events"] == 1


def test_anthropic_mode_falls_back_to_keyword_for_openrouter():
    schemas = [
        {"name": "read_file", "description": "Read files"},
        {"name": "github_search_code", "description": "Search code"},
        {"name": "slack_send_message", "description": "Send slack message"},
    ]
    out = select_tool_schemas_callback(
        "github search",
        [],
        schemas,
        "anthropic/claude-sonnet",
        "cli",
        provider="openrouter",
        config=ToolSlimmerConfig(
            mode="anthropic_tool_search",
            top_k=1,
            always_include=[],
            log_decisions=False,
            min_total_tools=0,
        ),
    )
    assert out == [schemas[1]]


def test_anthropic_tool_search_guardrail_uses_hot_set_metrics(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    schemas = [
        {"name": "read_file", "description": "Read files" + (" x" * 200)},
        {"name": "github_search_code", "toolset": "mcp:github", "description": "Search code" + (" y" * 200)},
        {"name": "slack_send_message", "toolset": "mcp:slack", "description": "Send slack message" + (" z" * 200)},
    ]

    out = select_tool_schemas_callback(
        "github search",
        [],
        schemas,
        "claude-sonnet",
        "cli",
        provider="anthropic",
        config=ToolSlimmerConfig(
            mode="anthropic_tool_search",
            top_k=1,
            always_include=[],
            log_decisions=True,
            min_total_tools=0,
            min_estimated_reduction_percent=5,
        ),
    )

    assert out is not None
    assert out[0]["name"] == "tool_search_tool_bm25"
    assert any(schema.get("defer_loading") is True for schema in out[1:])
    event = read_decisions()[0]
    assert event["metrics"]["metric_basis"] == "hot_set"
    assert event["metrics"]["selected"] == ["github_search_code"]
    assert event["metrics"]["anthropic_payload_tools"] == 4
    assert event["metrics"].get("skipped") is not True


def test_selector_skips_small_catalogs_before_ranking(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    schemas = [
        {"name": "read_file", "description": "Read files"},
        {"name": "search_files", "description": "Search files"},
    ]
    out = select_tool_schemas_callback(
        "search",
        [],
        schemas,
        "model",
        "cron",
        session_id="cron-1",
        config=ToolSlimmerConfig(top_k=1, always_include=[], min_total_tools=20),
    )

    assert out is None
    event = read_decisions()[0]
    assert event["metrics"]["skipped"] is True
    assert event["metrics"]["skip_reason"] == "below_min_total_tools"
    assert event["metrics"]["selection_ms"] >= 0


def test_selector_skips_low_reduction_results(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    schemas = [
        {"name": "read_file", "description": "Read files"},
        {"name": "search_files", "description": "Search files"},
        {"name": "terminal", "description": "Run commands"},
    ]
    out = select_tool_schemas_callback(
        "search",
        [],
        schemas,
        "model",
        "cron",
        session_id="cron-1",
        config=ToolSlimmerConfig(
            top_k=1,
            always_include=["read_file", "search_files", "terminal"],
            min_total_tools=0,
            min_estimated_reduction_percent=99,
        ),
    )

    assert out == schemas
    event = read_decisions()[0]
    assert event["metrics"]["skipped"] is True
    assert event["metrics"]["skip_reason"] == "below_min_estimated_reduction_percent"
    assert summarize_decisions(require_session=True)["totals"]["skipped_events"] == 1


def test_pre_llm_and_selector_hooks_registered():
    calls = []

    class Ctx:
        def register_hook(self, name, callback):
            calls.append((name, callback))

    assert maybe_register_selector_hook(Ctx()) is True
    assert [name for name, _ in calls] == ["pre_llm_call", "select_tool_schemas"]


def test_selector_hook_registration_fails_safe_when_unknown_hook_rejected():
    calls = []

    class Ctx:
        valid_hooks = {"pre_llm_call"}

        def register_hook(self, name, callback):
            calls.append(name)
            if name not in self.valid_hooks:
                raise ValueError(name)

    assert maybe_register_selector_hook(Ctx()) is False
    assert calls == ["pre_llm_call"]


def test_doctor_reports_invalid_config_without_crashing(tmp_path):
    from argparse import Namespace
    from hermes_tool_slimmer.cli import handle_cli

    path = tmp_path / "config.yaml"
    path.write_text("tool_slimmer:\n  mode: definitely_bad\n")
    assert handle_cli(Namespace(command="doctor", config=str(path), schemas=None, provider=None, model=None)) == 0


def test_doctor_uses_provider_model_for_anthropic_capability(tmp_path):
    from hermes_tool_slimmer.cli import run_doctor

    path = tmp_path / "config.yaml"
    path.write_text("tool_slimmer:\n  mode: anthropic_tool_search\n")
    openrouter = run_doctor(str(path), provider="openrouter", model="anthropic/claude")
    native = run_doctor(str(path), provider="anthropic", model="claude-sonnet")
    assert openrouter["checks"]["anthropic_tool_search"]["status"] == "fail"
    assert native["checks"]["anthropic_tool_search"]["status"] == "pass"


def test_doctor_reports_malformed_yaml_without_crashing(tmp_path):
    from hermes_tool_slimmer.cli import run_doctor

    path = tmp_path / "config.yaml"
    path.write_text("tool_slimmer:\n  mode: [bad\n")
    result = run_doctor(str(path))
    assert result["ok"] is False
    assert result["checks"]["config"]["status"] == "fail"
    assert result["checks"]["plugin_enabled"]["status"] == "warn"


def test_dashboard_plugin_api_reports_status_and_summary(monkeypatch, tmp_path):
    fastapi = pytest.importorskip("fastapi")
    testclient = pytest.importorskip("fastapi.testclient")

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_CONFIG", raising=False)
    select_tool_schemas_callback(
        "read",
        [],
        [{"name": "read_file", "description": "Read files"}, {"name": "terminal", "description": "Run commands"}],
        "model",
        "dashboard",
        config=ToolSlimmerConfig(top_k=1, always_include=[], min_total_tools=0),
    )

    plugin_path = Path(__file__).resolve().parents[1] / "dashboard-plugin" / "tool-slimmer" / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("tool_slimmer_dashboard_plugin", plugin_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    app = fastapi.FastAPI()
    app.include_router(module.router)
    with testclient.TestClient(app) as client:
        status = client.get("/status")
        summary = client.get("/summary")
        events = client.get("/events?limit=1")
        advisor = client.get("/advisor")
        privacy = client.get("/privacy")
        eval_report = client.get("/eval-report")
        index_before = client.get("/index")
        rebuilt = client.post(
            "/index/rebuild",
            json={
                "schemas": [
                    {"name": "read_file", "description": "Read files"},
                    {"name": "terminal", "description": "Run commands"},
                ],
            },
        )
        index_after = client.get("/index")

    assert status.status_code == 200
    assert status.json()["config"]["enabled"] is True
    assert summary.status_code == 200
    assert summary.json()["summary"]["totals"]["events"] == 1
    assert summary.json()["all_summary"]["totals"]["events"] == 1
    assert events.json()["events"][0]["metrics"]["selected"] == ["read_file"]
    assert advisor.status_code == 200
    assert advisor.json()["advisor"]["ok"] is True
    assert privacy.status_code == 200
    assert privacy.json()["privacy"]["raw_prompts_logged"] is False
    assert eval_report.status_code == 200
    assert "# Tool Slimmer Eval Report" in eval_report.json()["markdown"]
    assert index_before.status_code == 200
    assert index_before.json()["index"]["exists"] is False
    assert rebuilt.status_code == 200
    assert rebuilt.json()["source"] == "payload"
    assert rebuilt.json()["index"]["total_tools"] == 2
    assert index_after.json()["index"]["exists"] is True
    assert index_after.json()["index"]["documents"][0]["name"] == "read_file"
