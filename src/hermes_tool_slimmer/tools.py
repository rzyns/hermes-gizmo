from __future__ import annotations

import json
import os
from typing import Any

from .config import ToolSlimmerConfig, load_config
from .index_store import IndexStore
from .selector import ToolSelector
from .two_pass import hydration_response

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

    store = IndexStore()
    snapshot_schemas: list[dict[str, Any]] = []
    platform = None
    if isinstance(args, dict):
        platform = args.get("platform")
    platform = (
        platform
        or kwargs.get("platform")
        or os.environ.get("HERMES_PLATFORM")
        or os.environ.get("HERMES_SESSION_SOURCE")
    )
    snapshot_candidates: list[list[dict[str, Any]]] = []
    if platform:
        snapshot = store.load_live_schema_snapshot(str(platform))
        if snapshot:
            schemas = snapshot.get("schemas")
            if isinstance(schemas, list):
                snapshot_candidates.append(schemas)
    latest_snapshot = store.load_live_schema_snapshot("latest")
    if latest_snapshot:
        schemas = latest_snapshot.get("schemas")
        if isinstance(schemas, list):
            snapshot_candidates.append(schemas)
    latest_schemas = store.load_live_schemas(min_total_tools=0, require_session=False)
    if latest_schemas:
        snapshot_candidates.append(latest_schemas)
    if snapshot_candidates:
        snapshot_schemas = max(snapshot_candidates, key=len)

    if not args.get("allow_catalog_fallback"):
        return [], "none"
    live = _live_hermes_schemas()
    if live and (len(live) >= len(snapshot_schemas) or not platform):
        try:
            store.ensure(live)
        except Exception:
            pass
        return live, "live"
    if snapshot_schemas:
        try:
            store.ensure(snapshot_schemas)
        except Exception:
            pass
        return snapshot_schemas, "live_request"
    indexed = _indexed_schemas()
    if indexed:
        return indexed, "index"
    return [], "none"


def tool_slimmer_status(args: dict, **kwargs: Any) -> str:
    try:
        cfg = load_config(args.get("config_path") if isinstance(args, dict) else None)
        store = IndexStore()
        index = store.load()
        return _json(
            {
                "ok": True,
                "enabled": cfg.enabled,
                "mode": cfg.mode,
                "top_k": cfg.top_k,
                "two_pass": cfg.two_pass.__dict__,
                "index": {
                    "path": str(store.path),
                    "exists": index is not None,
                    "total_tools": (index or {}).get("total_tools", 0),
                },
            }
        )
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


def tool_slimmer_hydrate_tools(args: dict, **kwargs: Any) -> str:
    tools = args.get("tools") if isinstance(args, dict) else None
    if isinstance(tools, str):
        requested = [tools]
    elif isinstance(tools, list):
        requested = [str(item) for item in tools if item is not None]
    else:
        requested = []
    reason = args.get("reason") if isinstance(args, dict) else None
    cfg = load_config(args.get("config_path")) if isinstance(args, dict) else load_config()
    return _json(
        hydration_response(
            requested,
            reason=str(reason) if reason else None,
            limit=cfg.two_pass.hydrate_limit,
        )
    )


def tool_slimmer_select(args: dict, **kwargs: Any) -> str:
    try:
        cfg = load_config(args.get("config_path"))
        cfg = cfg.for_context(platform=args.get("platform"), profile=args.get("profile"))
        mode = args.get("mode")
        if mode == "eager":
            return _json({"ok": False, "error": "mode_not_allowed", "message": "eager mode is not available through the model-callable selector."})
        if mode is not None:
            cfg = ToolSlimmerConfig.from_mapping(
                {**cfg.__dict__, "mode": mode, "anthropic": cfg.anthropic.__dict__, "two_pass": cfg.two_pass.__dict__}
            )
        schemas, schema_source = _resolve_schemas(args, kwargs)
        if not schemas:
            return _json(
                {
                    "ok": False,
                    "error": "no_schemas_available",
                    "schema_source": schema_source,
                    "message": "Provide schemas, or explicitly set allow_catalog_fallback to use live/indexed tool catalogs.",
                }
            )
        query = args.get("query") or args.get("text") or ""
        result = ToolSelector(cfg).select(query, schemas)
        return _json({"ok": True, "mode": result.mode, "schema_source": schema_source, "schema_count": len(schemas), "selected": result.selected_names, "scores": result.scores, "score_details": result.score_details, "fail_open": result.fail_open, "reason": result.reason})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})
