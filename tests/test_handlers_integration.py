import json
import importlib.util
from pathlib import Path

import pytest

from hermes_tool_slimmer.commands import handle_slash_command
from hermes_tool_slimmer.config import ToolSlimmerConfig
from hermes_tool_slimmer.integration import maybe_register_selector_hook, select_tool_schemas_callback
from hermes_tool_slimmer.metrics import read_decisions, summarize_decisions
from hermes_tool_slimmer.tools import tool_slimmer_select, tool_slimmer_status


def test_plugin_handlers_return_json_strings(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    status = tool_slimmer_status({})
    select = tool_slimmer_select({"query": "read", "schemas": [{"name": "read_file", "description": "Read"}]})
    slash = handle_slash_command("select read", schemas=[{"name": "read_file", "description": "Read"}])
    assert json.loads(status)["ok"] is True
    assert json.loads(select)["ok"] is True
    assert json.loads(slash)["ok"] is True


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
        config=ToolSlimmerConfig(top_k=1, always_include=[]),
    )
    assert out == [schemas[1]]

    events = read_decisions()
    assert len(events) == 1
    assert events[0]["context"]["provider"] == "test-provider"
    assert events[0]["metrics"]["selected"] == ["search_files"]
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
        config=ToolSlimmerConfig(top_k=1, always_include=[]),
    )
    select_tool_schemas_callback(
        "search",
        [],
        schemas,
        "model",
        "tui",
        session_id="session-1",
        config=ToolSlimmerConfig(top_k=1, always_include=[]),
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
        ),
    )
    assert out == [schemas[1]]


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
        config=ToolSlimmerConfig(top_k=1, always_include=[]),
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

    assert status.status_code == 200
    assert status.json()["config"]["enabled"] is True
    assert summary.status_code == 200
    assert summary.json()["summary"]["totals"]["events"] == 1
    assert summary.json()["all_summary"]["totals"]["events"] == 1
    assert events.json()["events"][0]["metrics"]["selected"] == ["read_file"]
