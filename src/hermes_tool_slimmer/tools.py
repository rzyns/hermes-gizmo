from __future__ import annotations

import json
from typing import Any

from .config import ToolSlimmerConfig, load_config
from .index_store import IndexStore
from .selector import ToolSelector


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def tool_slimmer_status(args: dict, **kwargs: Any) -> str:
    try:
        cfg = load_config(args.get("config_path") if isinstance(args, dict) else None)
        store = IndexStore()
        index = store.load()
        return _json({"ok": True, "enabled": cfg.enabled, "mode": cfg.mode, "top_k": cfg.top_k, "index": {"path": str(store.path), "exists": index is not None, "total_tools": (index or {}).get("total_tools", 0)}})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def tool_slimmer_select(args: dict, **kwargs: Any) -> str:
    try:
        cfg = load_config(args.get("config_path"))
        if args.get("mode") is not None:
            cfg = ToolSlimmerConfig.from_mapping(
                {**cfg.__dict__, "mode": args.get("mode"), "anthropic": cfg.anthropic.__dict__}
            )
        schemas = args.get("schemas") or kwargs.get("schemas") or []
        query = args.get("query") or args.get("text") or ""
        result = ToolSelector(cfg).select(query, schemas)
        return _json({"ok": True, "mode": result.mode, "selected": result.selected_names, "scores": result.scores, "fail_open": result.fail_open, "reason": result.reason})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})
