from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


def _load_modules():
    try:
        from hermes_tool_slimmer.cli import run_doctor
        from hermes_tool_slimmer.config import load_config
        from hermes_tool_slimmer.index_store import IndexStore
        from hermes_tool_slimmer.metrics import read_decisions, summarize_decisions
    except Exception as exc:  # pragma: no cover - import environment dependent
        raise HTTPException(
            status_code=503,
            detail={"error": "tool_slimmer_unavailable", "message": str(exc)},
        ) from exc
    return run_doctor, load_config, IndexStore, read_decisions, summarize_decisions


@router.get("/status")
async def status() -> dict[str, Any]:
    run_doctor, load_config, IndexStore, _read_decisions, _summarize_decisions = _load_modules()
    cfg = load_config()
    store = IndexStore()
    index = store.load() or {}
    return {
        "ok": True,
        "config": {
            "enabled": cfg.enabled,
            "mode": cfg.mode,
            "top_k": cfg.top_k,
            "dry_run": cfg.dry_run,
            "log_decisions": cfg.log_decisions,
            "fail_open": cfg.fail_open,
            "always_include": cfg.always_include,
            "never_defer": cfg.never_defer,
        },
        "index": {
            "path": str(store.path),
            "exists": bool(index),
            "total_tools": int(index.get("total_tools") or 0),
            "checksum": index.get("checksum"),
        },
        "doctor": run_doctor(),
    }


@router.get("/summary")
async def summary(limit: int = Query(default=1000, ge=1, le=10000)) -> dict[str, Any]:
    _run_doctor, _load_config, _IndexStore, _read_decisions, summarize_decisions = _load_modules()
    return {
        "ok": True,
        "summary": summarize_decisions(limit=limit, require_session=True),
        "all_summary": summarize_decisions(limit=limit),
    }


@router.get("/events")
async def events(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    _run_doctor, _load_config, _IndexStore, read_decisions, _summarize_decisions = _load_modules()
    return {"ok": True, "events": read_decisions(limit=limit)}
