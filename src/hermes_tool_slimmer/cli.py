from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from .anthropic_tool_search import supports_anthropic_tool_search
from .config import ToolSlimmerConfig, config_path, load_config
from .corpus import tool_name
from .index_store import IndexStore
from .metrics import reduction_metrics
from .selector import ToolSelector


def _load_schemas(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    target = Path(path).expanduser()
    if not target.is_file():
        return []
    try:
        data = yaml.safe_load(target.read_text())
    except (OSError, yaml.YAMLError):
        return []
    if isinstance(data, dict):
        schemas = data.get("tools") or data.get("schemas")
        if isinstance(schemas, list):
            return schemas
        indexed_schemas = _schemas_from_index(data)
        if indexed_schemas:
            return indexed_schemas
        return []
    return data if isinstance(data, list) else []


def _schemas_from_index(index: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(index, dict):
        return []
    documents = index.get("documents")
    if not isinstance(documents, list):
        return []
    out = []
    for doc in documents:
        if not isinstance(doc, dict) or not doc.get("name"):
            continue
        tokens = doc.get("tokens")
        token_text = " ".join(str(token) for token in tokens) if isinstance(tokens, list) else ""
        out.append(
            {
                "name": doc.get("name"),
                "toolset": doc.get("toolset"),
                "description": doc.get("text") or token_text,
            }
        )
    return out


def _load_prompts(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    target = Path(path).expanduser()
    if not target.is_file():
        return []
    try:
        data = yaml.safe_load(target.read_text())
    except (OSError, yaml.YAMLError):
        return []
    if isinstance(data, dict):
        prompts = data.get("prompts")
        return prompts if isinstance(prompts, list) else []
    return data if isinstance(data, list) else []


def _tool_names(schemas: list[dict[str, Any]]) -> set[str]:
    return {tool_name(schema) for schema in schemas}


def _check(status: str, message: str, detail: object | None = None) -> dict[str, object]:
    item: dict[str, object] = {"status": status, "message": message}
    if detail is not None:
        item["detail"] = detail
    return item


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def analyze_config(cfg: ToolSlimmerConfig, summary: dict[str, object] | None = None, indexed_tools: int = 0) -> dict[str, object]:
    totals = (summary or {}).get("totals") if isinstance(summary, dict) else {}
    averages = (summary or {}).get("averages") if isinstance(summary, dict) else {}
    totals = totals if isinstance(totals, dict) else {}
    averages = averages if isinstance(averages, dict) else {}
    events = int(totals.get("events") or 0)
    skipped = int(totals.get("skipped_events") or 0)
    recommendations: list[dict[str, object]] = []
    if events == 0:
        recommendations.append({"id": "collect_data", "severity": "info", "message": "No real selector events are available yet; keep decision logging on until the dashboard has enough data."})
    if len(cfg.always_include) > max(1, cfg.top_k):
        recommendations.append({"id": "review_always_include", "severity": "warn", "message": "always_include is larger than top_k; confirm every always-on tool is truly required.", "tools": cfg.always_include})
    if events and skipped / events > 0.5:
        recommendations.append({"id": "review_guardrails", "severity": "warn", "message": "More than half of recent selections were skipped by guardrails; review min_total_tools and min_estimated_reduction_percent."})
    if cfg.mode == "keyword" and not cfg.aliases:
        recommendations.append({"id": "add_aliases", "severity": "info", "message": "Keyword mode is deterministic; add aliases for common user wording that differs from tool names."})
    if indexed_tools == 0:
        recommendations.append({"id": "rebuild_index", "severity": "info", "message": "The persisted tool index is empty; rebuild it from the dashboard after tool changes."})
    return {
        "ok": True,
        "config": {"mode": cfg.mode, "top_k": cfg.top_k, "always_include": cfg.always_include, "min_total_tools": cfg.min_total_tools, "min_estimated_reduction_percent": cfg.min_estimated_reduction_percent, "aliases": cfg.aliases},
        "observed": {"events": events, "skipped_events": skipped, "average_reduction_percent": averages.get("reduction_percent", 0), "indexed_tools": indexed_tools},
        "recommendations": recommendations,
    }


def privacy_inventory() -> dict[str, object]:
    return {
        "ok": True,
        "raw_prompts_logged": False,
        "decision_log_path": str(IndexStore().root / "decisions.jsonl"),
        "event_fields": ["timestamp", "metrics", "context"],
        "context_fields": ["provider", "model", "platform", "session_id", "dry_run", "schema_count"],
        "metric_fields": [
            "mode",
            "total_tools",
            "selected_tools",
            "schema_bytes_before",
            "schema_bytes_after",
            "schema_bytes_saved",
            "approx_tokens_before",
            "approx_tokens_after",
            "approx_tokens_saved",
            "estimated_reduction_percent",
            "always_included",
            "selected",
            "selection_ms",
            "skipped",
            "skip_reason",
            "selected_scores",
            "top_candidates",
            "expanded_query_tokens",
        ],
        "notes": [
            "Raw user prompts are not written to decisions.jsonl.",
            "Dashboard headline totals exclude events without a session_id.",
            "Score details include tool names and numeric ranking components.",
        ],
    }


def eval_prompts(cfg: ToolSlimmerConfig, schemas: list[dict[str, Any]], prompts: list[dict[str, Any]]) -> dict[str, object]:
    rows = []
    hits = 0
    fail_open_count = 0
    selector = ToolSelector(cfg)
    total_reduction = 0.0
    total_selected = 0
    for prompt in prompts:
        if not isinstance(prompt, dict):
            continue
        result = selector.select(str(prompt.get("text") or ""), schemas)
        metrics = reduction_metrics(cfg.mode, schemas, result.selected, result.always_included)
        expected = set(prompt.get("expected_any", []))
        hit = bool(expected & set(result.selected_names)) if expected else None
        if hit:
            hits += 1
        if result.fail_open:
            fail_open_count += 1
        total_selected += len(result.selected_names)
        total_reduction += _safe_float(metrics.get("estimated_reduction_percent"))
        rows.append({"name": prompt.get("name"), "selected": result.selected_names, "expected_included": hit, "reduction_percent": metrics["estimated_reduction_percent"], "fail_open": result.fail_open, "reason": result.reason})
    expected_rows = [row for row in rows if row["expected_included"] is not None]
    return {
        "summary": {
            "prompts": len(rows),
            "expected_prompts": len(expected_rows),
            "hit_rate": round(hits / len(expected_rows), 3) if expected_rows else None,
            "average_reduction_percent": round(total_reduction / len(rows), 1) if rows else 0.0,
            "average_selected_tools": round(total_selected / len(rows), 1) if rows else 0.0,
            "fail_open_count": fail_open_count,
        },
        "rows": rows,
    }


def eval_markdown(report: dict[str, object]) -> str:
    summary = report.get("summary") if isinstance(report, dict) else {}
    rows = report.get("rows") if isinstance(report, dict) else []
    summary = summary if isinstance(summary, dict) else {}
    rows = rows if isinstance(rows, list) else []
    lines = [
        "# Tool Slimmer Eval Report",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Prompts | {summary.get('prompts', 0)} |",
        f"| Expected prompts | {summary.get('expected_prompts', 0)} |",
        f"| Hit rate | {summary.get('hit_rate')} |",
        f"| Average selected tools | {summary.get('average_selected_tools', 0)} |",
        f"| Average reduction | {summary.get('average_reduction_percent', 0)}% |",
        f"| Fail-open count | {summary.get('fail_open_count', 0)} |",
        "",
        "| Prompt | Expected hit | Reduction | Fail-open | Selected |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        if not isinstance(row, dict):
            continue
        selected = ", ".join(str(item) for item in row.get("selected", []))
        lines.append(f"| {row.get('name') or ''} | {row.get('expected_included')} | {row.get('reduction_percent')}% | {row.get('fail_open')} | {selected} |")
    lines.append("")
    return "\n".join(lines)


def run_doctor(
    config_arg: str | None = None,
    schemas_path: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, object]:
    checks: dict[str, dict[str, object]] = {}
    cfg: ToolSlimmerConfig | None = None
    target = Path(config_arg).expanduser() if config_arg else config_path()
    try:
        if config_arg and not target.is_file():
            raise FileNotFoundError(str(target))
        cfg = load_config(config_arg)
        checks["config"] = _check("pass", "tool_slimmer config is valid", {"mode": cfg.mode, "top_k": cfg.top_k})
    except Exception as exc:
        checks["config"] = _check("fail", "tool_slimmer config is invalid", str(exc))
        cfg = ToolSlimmerConfig(enabled=False)

    checks["hermes_importable"] = _check(
        "pass" if importlib.util.find_spec("hermes_cli") else "warn",
        "Hermes Python modules are importable" if importlib.util.find_spec("hermes_cli") else "Hermes Python modules were not found in this environment",
    )

    enabled_detail: object = "config file not found"
    enabled_status = "warn"
    if target.is_file():
        try:
            data = yaml.safe_load(target.read_text()) or {}
            enabled = data.get("plugins", {}).get("enabled", []) if isinstance(data, dict) else []
            enabled_status = "pass" if "tool-slimmer" in enabled else "warn"
            enabled_detail = enabled
        except Exception as exc:
            enabled_status = "warn"
            enabled_detail = f"config unreadable: {exc}"
    checks["plugin_enabled"] = _check(
        enabled_status,
        "tool-slimmer is listed in plugins.enabled"
        if enabled_status == "pass"
        else "tool-slimmer is not listed in plugins.enabled",
        enabled_detail,
    )

    store = IndexStore()
    try:
        probe = store.root / ".doctor-write-test" if store.root else store.path.parent / ".doctor-write-test"
        probe.write_text("ok")
        probe.unlink()
        index = store.load()
        checks["index_store"] = _check("pass", "index directory is readable/writable", {"path": str(store.path), "indexed_tools": (index or {}).get("total_tools", 0)})
    except Exception as exc:
        index = None
        checks["index_store"] = _check("fail", "index directory is not readable/writable", str(exc))

    schemas = _load_schemas(schemas_path)
    schema_source = "supplied schemas"
    if not schemas:
        schemas = _schemas_from_index(index)
        schema_source = "tool index"
    if schemas:
        names = _tool_names(schemas)
        missing = [name for name in cfg.always_include if name not in names]
        checks["always_include"] = _check(
            "pass" if not missing else "warn",
            f"always-included tools exist in {schema_source}" if not missing else f"some always-included tools are absent from {schema_source}",
            missing,
        )
    else:
        checks["always_include"] = _check("warn", "no schemas supplied; cannot validate always_include")

    selector_supported = False
    try:
        import hermes_cli.plugins as plugins  # type: ignore[import-not-found]

        selector_supported = "select_tool_schemas" in getattr(plugins, "VALID_HOOKS", set())
        checks["core_selector_hook"] = _check(
            "pass" if selector_supported else "warn",
            "Hermes core advertises select_tool_schemas"
            if selector_supported
            else "Hermes core does not advertise select_tool_schemas; apply docs/hermes-core-selector-hook.patch",
        )
    except Exception:
        checks["core_selector_hook"] = _check(
            "warn",
            "Hermes core not importable here; apply/check docs/hermes-core-selector-hook.patch",
        )

    if cfg.mode == "anthropic_tool_search":
        supported = supports_anthropic_tool_search(
            provider, model, cfg.anthropic.tool_search_supported
        )
        if supported:
            checks["anthropic_tool_search"] = _check(
                "pass",
                "provider path supports Anthropic Tool Search",
                {"provider": provider, "model": model},
            )
        else:
            checks["anthropic_tool_search"] = _check(
                "fail",
                "anthropic_tool_search mode requires native Anthropic provider or explicit tool_search_supported for this provider path",
                {"provider": provider, "model": model},
            )
    else:
        checks["anthropic_tool_search"] = _check("pass", "Anthropic Tool Search mode is not active")
    return {"ok": all(v["status"] != "fail" for v in checks.values()), "checks": checks}


def setup_argparse(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to Hermes config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--schemas")
    doctor.add_argument("--provider")
    doctor.add_argument("--model")
    index = sub.add_parser("index")
    index_sub = index.add_subparsers(dest="index_command", required=True)
    rebuild = index_sub.add_parser("rebuild")
    rebuild.add_argument("--schemas", required=True)
    show = index_sub.add_parser("show")
    show.add_argument("--top", type=int, default=20)
    select = sub.add_parser("select")
    select.add_argument("query")
    select.add_argument("--schemas")
    bench = sub.add_parser("benchmark")
    bench.add_argument("--prompts", required=True)
    bench.add_argument("--schemas")
    eval_cmd = sub.add_parser("eval")
    eval_cmd.add_argument("--prompts", required=True)
    eval_cmd.add_argument("--schemas")
    eval_cmd.add_argument("--markdown", action="store_true")
    sub.add_parser("analyze-config")
    sub.add_parser("privacy")
    sub.add_parser("recommend-config")


def handle_cli(args: argparse.Namespace) -> int:
    if args.command == "doctor":
        print(
            json.dumps(
                run_doctor(
                    getattr(args, "config", None),
                    getattr(args, "schemas", None),
                    getattr(args, "provider", None),
                    getattr(args, "model", None),
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "privacy":
        print(json.dumps(privacy_inventory(), indent=2, sort_keys=True))
        return 0

    cfg = load_config(getattr(args, "config", None))
    if args.command == "status":
        store = IndexStore()
        index = store.load() or {}
        print(json.dumps({"enabled": cfg.enabled, "mode": cfg.mode, "top_k": cfg.top_k, "index_path": str(store.path), "total_tools_indexed": index.get("total_tools", 0), "core_integration": "active when Hermes exposes select_tool_schemas hook or applies docs/hermes-core-selector-hook.patch"}, indent=2))
        return 0
    if args.command == "index":
        store = IndexStore()
        if args.index_command == "rebuild":
            payload = store.rebuild(_load_schemas(args.schemas))
            print(json.dumps({"path": str(store.path), "checksum": payload["checksum"], "total_tools": payload["total_tools"]}, indent=2))
            return 0
        index = store.load() or {"documents": []}
        print(json.dumps(index.get("documents", [])[: args.top], indent=2))
        return 0
    if args.command == "select":
        schemas = _load_schemas(args.schemas)
        result = ToolSelector(cfg).select(args.query, schemas)
        print(json.dumps({"selected": result.selected_names, "scores": result.scores, "score_details": result.score_details, "fail_open": result.fail_open}, indent=2, sort_keys=True))
        return 0
    if args.command == "benchmark":
        schemas = _load_schemas(args.schemas)
        prompts = _load_prompts(args.prompts)
        rows = []
        selector = ToolSelector(cfg)
        for prompt in prompts:
            if not isinstance(prompt, dict):
                continue
            result = selector.select(str(prompt.get("text") or ""), schemas)
            metrics = reduction_metrics(cfg.mode, schemas, result.selected, result.always_included)
            expected = set(prompt.get("expected_any", []))
            rows.append({"name": prompt.get("name"), "selected": result.selected_names, "expected_included": bool(expected & set(result.selected_names)) if expected else None, "metrics": metrics})
        print(json.dumps({"benchmarks": rows}, indent=2))
        return 0
    if args.command == "eval":
        schemas = _load_schemas(args.schemas)
        prompts = _load_prompts(args.prompts)
        report = eval_prompts(cfg, schemas, prompts)
        print(eval_markdown(report) if getattr(args, "markdown", False) else json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.command == "analyze-config":
        from .metrics import summarize_decisions

        store = IndexStore()
        index = store.load() or {}
        print(json.dumps(analyze_config(cfg, summarize_decisions(require_session=True), int(index.get("total_tools") or 0)), indent=2, sort_keys=True))
        return 0
    if args.command == "recommend-config":
        print(yaml.safe_dump({"tool_slimmer": {"enabled": True, "mode": "keyword", "top_k": 8, "always_include": cfg.always_include, "min_total_tools": cfg.min_total_tools, "min_estimated_reduction_percent": cfg.min_estimated_reduction_percent, "fail_open": True, "dry_run": False}}, sort_keys=False))
        return 0
    raise ValueError(f"Unknown command {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes tool-slimmer")
    setup_argparse(parser)
    return handle_cli(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
