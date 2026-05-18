from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

router = APIRouter()


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _load_modules():
    try:
        from hermes_tool_slimmer.cli import analyze_config, eval_markdown, eval_prompts, privacy_inventory, run_doctor
        from hermes_tool_slimmer.config import load_config
        from hermes_tool_slimmer.index_store import IndexStore
        from hermes_tool_slimmer.metrics import read_decisions, summarize_decisions
    except Exception as exc:  # pragma: no cover - import environment dependent
        raise HTTPException(
            status_code=503,
            detail={"error": "tool_slimmer_unavailable", "message": str(exc)},
        ) from exc
    return analyze_config, eval_markdown, eval_prompts, privacy_inventory, run_doctor, load_config, IndexStore, read_decisions, summarize_decisions


def _summarize_index(store: Any) -> dict[str, Any]:
    index = store.load() or {}
    documents = index.get("documents") if isinstance(index.get("documents"), list) else []
    try:
        updated_at = store.path.stat().st_mtime
    except OSError:
        updated_at = None
    return {
        "path": str(store.path),
        "exists": bool(index),
        "total_tools": _safe_int(index.get("total_tools")),
        "checksum": index.get("checksum"),
        "updated_at": updated_at,
        "documents": [
            {
                "name": str(doc.get("name") or ""),
                "toolset": str(doc.get("toolset") or ""),
                "token_count": len(doc.get("tokens") or []),
            }
            for doc in documents[:50]
            if isinstance(doc, dict)
        ],
        "live_selection": {
            "uses_persisted_index": False,
            "message": "Hermes selection ranks the live request tool schemas in memory; the persisted index is for inspection, audits, and troubleshooting.",
        },
    }


def _last_live_request_schemas() -> list[dict[str, Any]]:
    try:
        from hermes_tool_slimmer.index_store import IndexStore
    except Exception:
        return []
    schemas = IndexStore().load_live_schemas()
    return schemas if schemas and all(isinstance(schema, dict) for schema in schemas) else []


def _live_hermes_schemas() -> tuple[list[dict[str, Any]], str]:
    last_live = _last_live_request_schemas()
    if last_live:
        return last_live, "live_request"

    try:
        from model_tools import get_tool_definitions  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - Hermes environment dependent
        raise HTTPException(
            status_code=400,
            detail={
                "error": "schemas_required",
                "message": "Hermes tool definitions are not importable in this process. Send a JSON body with a schemas array or rebuild from a running Hermes dashboard.",
                "cause": str(exc),
            },
        ) from exc

    try:
        schemas = get_tool_definitions(None, None, True)
    except TypeError:
        schemas = get_tool_definitions()  # type: ignore[call-arg]
    except Exception as exc:  # pragma: no cover - Hermes environment dependent
        raise HTTPException(
            status_code=400,
            detail={
                "error": "tool_definitions_unavailable",
                "message": "Hermes tool definitions could not be loaded for indexing.",
                "cause": str(exc),
            },
        ) from exc

    if not isinstance(schemas, list):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_tool_definitions", "message": "Hermes returned an unexpected tool definition payload."},
        )
    return schemas, "hermes"


@router.get("/status")
async def status() -> dict[str, Any]:
    _analyze_config, _eval_markdown, _eval_prompts, _privacy_inventory, run_doctor, load_config, IndexStore, _read_decisions, _summarize_decisions = _load_modules()
    config_error = None
    try:
        cfg = load_config()
    except Exception as exc:
        from hermes_tool_slimmer.config import ToolSlimmerConfig

        cfg = ToolSlimmerConfig(enabled=False)
        config_error = str(exc)
    store = IndexStore()
    index = store.load() or {}
    return {
        "ok": config_error is None,
        "error": config_error,
        "config": {
            "enabled": cfg.enabled,
            "mode": cfg.mode,
            "top_k": cfg.top_k,
            "dry_run": cfg.dry_run,
            "log_decisions": cfg.log_decisions,
            "fail_open": cfg.fail_open,
            "min_total_tools": cfg.min_total_tools,
            "min_estimated_reduction_percent": cfg.min_estimated_reduction_percent,
            "always_include": cfg.always_include,
            "never_defer": cfg.never_defer,
            "aliases": cfg.aliases,
        },
        "index": {
            "path": str(store.path),
            "exists": bool(index),
            "total_tools": _safe_int(index.get("total_tools")),
            "checksum": index.get("checksum"),
        },
        "doctor": run_doctor(),
    }


@router.get("/index")
async def index_status() -> dict[str, Any]:
    _analyze_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, _load_config, IndexStore, _read_decisions, _summarize_decisions = _load_modules()
    return {"ok": True, "index": _summarize_index(IndexStore())}


@router.post("/index/rebuild")
async def rebuild_index(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    _analyze_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, _load_config, IndexStore, _read_decisions, _summarize_decisions = _load_modules()
    source = "hermes"
    schemas: list[dict[str, Any]]
    raw_schemas = (payload or {}).get("schemas") or (payload or {}).get("tools")
    if raw_schemas is None:
        schemas, source = _live_hermes_schemas()
    elif isinstance(raw_schemas, list):
        source = "payload"
        schemas = raw_schemas
    else:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_schemas", "message": "Expected schemas to be a JSON array."},
        )

    store = IndexStore()
    store.rebuild(schemas)
    return {"ok": True, "source": source, "index": _summarize_index(store)}


@router.get("/summary")
async def summary(limit: int = Query(default=1000, ge=1, le=10000)) -> dict[str, Any]:
    _analyze_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, _load_config, _IndexStore, _read_decisions, summarize_decisions = _load_modules()
    return {
        "ok": True,
        "summary": summarize_decisions(limit=limit, require_session=True),
        "all_summary": summarize_decisions(limit=limit),
    }


@router.get("/events")
async def events(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    _analyze_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, _load_config, _IndexStore, read_decisions, _summarize_decisions = _load_modules()
    return {"ok": True, "events": read_decisions(limit=limit)}


@router.get("/advisor")
async def advisor(limit: int = Query(default=1000, ge=1, le=10000)) -> dict[str, Any]:
    analyze_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, load_config, IndexStore, _read_decisions, summarize_decisions = _load_modules()
    try:
        cfg = load_config()
    except Exception as exc:
        from hermes_tool_slimmer.config import ToolSlimmerConfig

        cfg = ToolSlimmerConfig(enabled=False)
        return {"ok": False, "error": str(exc), "advisor": analyze_config(cfg, summarize_decisions(limit=limit, require_session=True), 0)}
    index = IndexStore().load() or {}
    return {"ok": True, "advisor": analyze_config(cfg, summarize_decisions(limit=limit, require_session=True), _safe_int(index.get("total_tools")))}


@router.get("/privacy")
async def privacy() -> dict[str, Any]:
    _analyze_config, _eval_markdown, _eval_prompts, privacy_inventory, _run_doctor, _load_config, _IndexStore, _read_decisions, _summarize_decisions = _load_modules()
    return {"ok": True, "privacy": privacy_inventory()}


@router.get("/eval-report")
async def eval_report() -> dict[str, Any]:
    _analyze_config, eval_markdown, eval_prompts, _privacy_inventory, _run_doctor, load_config, _IndexStore, _read_decisions, _summarize_decisions = _load_modules()
    from pathlib import Path
    import yaml

    def _load_example_list(path: Path, key: str) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError):
            return []
        if isinstance(data, dict):
            value = data.get(key)
            return value if isinstance(value, list) else []
        return data if isinstance(data, list) else []

    plugin_root = Path(__file__).resolve().parents[1]
    repo_root = Path(__file__).resolve().parents[3]
    schemas_path = plugin_root / "examples" / "tools.yaml"
    prompts_path = plugin_root / "examples" / "prompts.yaml"
    if not schemas_path.exists():
        schemas_path = repo_root / "examples" / "tools.yaml"
    if not prompts_path.exists():
        prompts_path = repo_root / "examples" / "prompts.yaml"
    schemas = _load_example_list(schemas_path, "tools")
    prompts = _load_example_list(prompts_path, "prompts")
    try:
        cfg = load_config()
    except Exception:
        from hermes_tool_slimmer.config import ToolSlimmerConfig

        cfg = ToolSlimmerConfig(enabled=False)
    report = eval_prompts(cfg, schemas, prompts)
    return {"ok": True, "markdown": eval_markdown(report), "report": report}
