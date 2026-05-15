from __future__ import annotations

import json
import time
from collections import Counter
from typing import Iterable

from .config import hermes_home
from .corpus import tool_name
from .types import Schema


def schema_bytes(schemas: Iterable[Schema]) -> int:
    return len(json.dumps(list(schemas), sort_keys=True, separators=(",", ":")).encode("utf-8"))


def approx_tokens(byte_count: int) -> int:
    return round(byte_count / 4)


def reduction_metrics(mode: str, original: list[Schema], selected: list[Schema], always_included: list[str] | None = None) -> dict[str, object]:
    before = schema_bytes(original)
    after = schema_bytes(selected)
    reduction = 0.0 if before == 0 else round(((before - after) / before) * 100, 1)
    return {
        "mode": mode,
        "total_tools": len(original),
        "selected_tools": len(selected),
        "schema_bytes_before": before,
        "schema_bytes_after": after,
        "approx_tokens_before": approx_tokens(before),
        "approx_tokens_after": approx_tokens(after),
        "estimated_reduction_percent": reduction,
        "always_included": always_included or [],
        "selected": [tool_name(schema) for schema in selected],
        "token_estimate_note": "Approximate tokens use serialized JSON bytes / 4.",
    }


def decision_log_path() -> str:
    return str(hermes_home() / "tool-slimmer" / "decisions.jsonl")


def record_decision(metrics: dict[str, object], context: dict[str, object] | None = None) -> None:
    """Append one selector decision for dashboard/ops visibility."""
    path = hermes_home() / "tool-slimmer" / "decisions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": time.time(),
        "metrics": metrics,
        "context": context or {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, default=str, separators=(",", ":")) + "\n")


def read_decisions(limit: int = 200) -> list[dict[str, object]]:
    path = hermes_home() / "tool-slimmer" / "decisions.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    events: list[dict[str, object]] = []
    for line in lines[-max(1, limit) :]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def summarize_decisions(
    limit: int = 1000,
    *,
    require_session: bool = False,
) -> dict[str, object]:
    events = read_decisions(limit)
    ignored_events = 0
    if require_session:
        filtered_events = []
        for event in events:
            context = event.get("context") if isinstance(event, dict) else {}
            if isinstance(context, dict) and context.get("session_id"):
                filtered_events.append(event)
            else:
                ignored_events += 1
        events = filtered_events
    totals = {
        "events": len(events),
        "schema_bytes_before": 0,
        "schema_bytes_after": 0,
        "schema_bytes_saved": 0,
        "approx_tokens_before": 0,
        "approx_tokens_after": 0,
        "approx_tokens_saved": 0,
        "selected_tools": 0,
        "total_tools": 0,
    }
    modes: Counter[str] = Counter()
    providers: Counter[str] = Counter()
    platforms: Counter[str] = Counter()
    selected: Counter[str] = Counter()
    reductions: list[float] = []

    for event in events:
        metrics = event.get("metrics") if isinstance(event, dict) else {}
        context = event.get("context") if isinstance(event, dict) else {}
        if not isinstance(metrics, dict):
            continue
        before = int(metrics.get("schema_bytes_before") or 0)
        after = int(metrics.get("schema_bytes_after") or 0)
        tokens_before = int(metrics.get("approx_tokens_before") or 0)
        tokens_after = int(metrics.get("approx_tokens_after") or 0)
        totals["schema_bytes_before"] += before
        totals["schema_bytes_after"] += after
        totals["schema_bytes_saved"] += max(0, before - after)
        totals["approx_tokens_before"] += tokens_before
        totals["approx_tokens_after"] += tokens_after
        totals["approx_tokens_saved"] += max(0, tokens_before - tokens_after)
        totals["selected_tools"] += int(metrics.get("selected_tools") or 0)
        totals["total_tools"] += int(metrics.get("total_tools") or 0)
        try:
            reductions.append(float(metrics.get("estimated_reduction_percent") or 0.0))
        except (TypeError, ValueError):
            pass
        mode = metrics.get("mode")
        if mode:
            modes[str(mode)] += 1
        if isinstance(context, dict):
            provider = context.get("provider")
            platform = context.get("platform")
            if provider:
                providers[str(provider)] += 1
            if platform:
                platforms[str(platform)] += 1
        for name in metrics.get("selected") or []:
            selected[str(name)] += 1

    avg_reduction = round(sum(reductions) / len(reductions), 1) if reductions else 0.0
    avg_selected = round(totals["selected_tools"] / totals["events"], 1) if totals["events"] else 0.0
    avg_total = round(totals["total_tools"] / totals["events"], 1) if totals["events"] else 0.0
    return {
        "log_path": decision_log_path(),
        "ignored_events": ignored_events,
        "require_session": require_session,
        "last_event_at": events[-1].get("timestamp") if events else None,
        "totals": totals,
        "averages": {
            "reduction_percent": avg_reduction,
            "selected_tools": avg_selected,
            "total_tools": avg_total,
        },
        "modes": dict(modes.most_common()),
        "providers": dict(providers.most_common()),
        "platforms": dict(platforms.most_common()),
        "top_selected_tools": dict(selected.most_common(20)),
        "recent": events[-20:],
    }
