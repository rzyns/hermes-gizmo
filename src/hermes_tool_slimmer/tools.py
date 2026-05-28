from __future__ import annotations

import json
from typing import Any

from .config import ToolSlimmerConfig, load_config
from .index_store import IndexStore
from .selector import ToolSelector

FULL_TOOLS_REQUEST_MARKER = "tool_slimmer_full_tools_requested"


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _live_hermes_schemas() -> list[dict[str, Any]]:
    try:
        from model_tools import get_tool_definitions  # type: ignore[import-not-found]
    except Exception:
        return []
    try:
        schemas = get_tool_definitions(None, None, True)
    except TypeError:
        schemas = get_tool_definitions()  # type: ignore[call-arg]
    except Exception:
        return []
    return schemas if isinstance(schemas, list) else []


def _indexed_schemas() -> list[dict[str, Any]]:
    index = IndexStore().load() or {}
    docs_raw = index.get("documents")
    docs: list[Any] = docs_raw if isinstance(docs_raw, list) else []
    schemas = []
    for doc in docs:
        if not isinstance(doc, dict) or not doc.get("name"):
            continue
        tokens = doc.get("tokens")
        token_text = " ".join(str(token) for token in tokens) if isinstance(tokens, list) else ""
        schemas.append({"name": doc.get("name"), "toolset": doc.get("toolset"), "description": doc.get("text") or token_text})
    return schemas


def _resolve_schemas(args: dict[str, Any], kwargs: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    provided = args.get("schemas") if isinstance(args, dict) and "schemas" in args else kwargs.get("schemas")
    if isinstance(provided, list):
        return provided, "provided"
    live = _live_hermes_schemas()
    if live:
        try:
            IndexStore().ensure(live)
        except Exception:
            pass
        return live, "live"
    last_live = IndexStore().load_live_schemas()
    if last_live:
        return last_live, "live_request"
    indexed = _indexed_schemas()
    if indexed:
        return indexed, "index"
    return [], "none"


def tool_slimmer_status(args: dict, **kwargs: Any) -> str:
    try:
        cfg = load_config(args.get("config_path") if isinstance(args, dict) else None)
        store = IndexStore()
        index = store.load()
        return _json({"ok": True, "enabled": cfg.enabled, "mode": cfg.mode, "top_k": cfg.top_k, "index": {"path": str(store.path), "exists": index is not None, "total_tools": (index or {}).get("total_tools", 0)}})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def tool_slimmer_request_full_tools(args: dict, **kwargs: Any) -> str:
    reason = args.get("reason") if isinstance(args, dict) else None
    payload: dict[str, Any] = {
        "ok": True,
        FULL_TOOLS_REQUEST_MARKER: True,
        "message": (
            "Full tool schemas requested for the next model call. Retry the original task "
            "after the tool list reloads; do not build substitute tools."
        ),
    }
    if reason:
        payload["reason"] = str(reason)
    return _json(payload)


def tool_slimmer_select(args: dict, **kwargs: Any) -> str:
    try:
        cfg = load_config(args.get("config_path"))
        cfg = cfg.for_context(platform=args.get("platform"), profile=args.get("profile"))
        if args.get("mode") is not None:
            cfg = ToolSlimmerConfig.from_mapping(
                {**cfg.__dict__, "mode": args.get("mode"), "anthropic": cfg.anthropic.__dict__}
            )
        schemas, schema_source = _resolve_schemas(args, kwargs)
        if not schemas:
            return _json({"ok": False, "error": "no_schemas_available", "message": "Provide schemas, run inside Hermes with live tool definitions, or rebuild the Tool Slimmer index."})
        query = args.get("query") or args.get("text") or ""
        result = ToolSelector(cfg).select(query, schemas)
        return _json({"ok": True, "mode": result.mode, "schema_source": schema_source, "schema_count": len(schemas), "selected": result.selected_names, "scores": result.scores, "score_details": result.score_details, "fail_open": result.fail_open, "reason": result.reason})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})
