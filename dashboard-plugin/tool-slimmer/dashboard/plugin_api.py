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
        from hermes_tool_slimmer.advisor import apply_recommended_config, apply_tool_preference, analyze_config, rollback_config
        from hermes_tool_slimmer.cli import eval_markdown, eval_prompts, privacy_inventory, run_doctor
        from hermes_tool_slimmer.config import load_config
        from hermes_tool_slimmer.index_store import IndexStore
        from hermes_tool_slimmer.metrics import read_decisions, summarize_decisions
    except Exception as exc:  # pragma: no cover - import environment dependent
        raise HTTPException(
            status_code=503,
            detail={"error": "tool_slimmer_unavailable", "message": str(exc)},
        ) from exc
    return analyze_config, apply_recommended_config, apply_tool_preference, rollback_config, eval_markdown, eval_prompts, privacy_inventory, run_doctor, load_config, IndexStore, read_decisions, summarize_decisions


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


def _hermes_tool_definitions() -> list[dict[str, Any]]:
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
    return schemas


def _live_hermes_schemas() -> tuple[list[dict[str, Any]], str]:
    candidates: list[tuple[list[dict[str, Any]], str]] = []
    hermes_error: HTTPException | None = None
    try:
        schemas = _hermes_tool_definitions()
    except HTTPException as exc:
        hermes_error = exc
    else:
        candidates.append((schemas, "hermes"))
    last_live = _last_live_request_schemas()
    if last_live:
        candidates.append((last_live, "live_request"))
    if candidates:
        return max(candidates, key=lambda item: len(item[0]))
    if hermes_error is not None:
        raise hermes_error
    raise HTTPException(
        status_code=400,
        detail={"error": "tool_definitions_unavailable", "message": "No Hermes tool definitions or live request snapshot are available."},
    )


@router.get("/status")
async def status() -> dict[str, Any]:
    _analyze_config, _apply_recommended_config, _apply_tool_preference, _rollback_config, _eval_markdown, _eval_prompts, _privacy_inventory, run_doctor, load_config, IndexStore, _read_decisions, _summarize_decisions = _load_modules()
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
            "min_score": cfg.min_score,
            "always_include": cfg.always_include,
            "always_exclude": cfg.disabled_tools,
            "disabled_tools": cfg.disabled_tools,
            "disabled_toolsets": cfg.disabled_toolsets,
            "never_defer": cfg.never_defer,
            "aliases": cfg.aliases,
            "profiles": cfg.profiles,
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
    _analyze_config, _apply_recommended_config, _apply_tool_preference, _rollback_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, _load_config, IndexStore, _read_decisions, _summarize_decisions = _load_modules()
    return {"ok": True, "index": _summarize_index(IndexStore())}


@router.post("/index/rebuild")
async def rebuild_index(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    _analyze_config, _apply_recommended_config, _apply_tool_preference, _rollback_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, _load_config, IndexStore, _read_decisions, _summarize_decisions = _load_modules()
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
    current = store.load() or {}
    current_total = _safe_int(current.get("total_tools"))
    if raw_schemas is None and current_total > len(schemas):
        return {
            "ok": True,
            "source": source,
            "preserved_existing_index": True,
            "message": (
                f"Rebuild source only exposed {len(schemas)} tools; preserved existing {current_total}-tool index "
                "to avoid replacing a fuller live gateway catalog with a smaller standalone catalog."
            ),
            "index": _summarize_index(store),
        }
    store.rebuild(schemas)
    return {"ok": True, "source": source, "index": _summarize_index(store)}


@router.get("/summary")
async def summary(limit: int = Query(default=1000, ge=1, le=10000)) -> dict[str, Any]:
    _analyze_config, _apply_recommended_config, _apply_tool_preference, _rollback_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, _load_config, _IndexStore, _read_decisions, summarize_decisions = _load_modules()
    return {
        "ok": True,
        "summary": summarize_decisions(limit=limit, require_session=True),
        "all_summary": summarize_decisions(limit=limit),
    }


@router.get("/events")
async def events(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    _analyze_config, _apply_recommended_config, _apply_tool_preference, _rollback_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, _load_config, _IndexStore, read_decisions, _summarize_decisions = _load_modules()
    return {"ok": True, "events": read_decisions(limit=limit)}


@router.get("/advisor")
async def advisor(limit: int = Query(default=1000, ge=1, le=10000)) -> dict[str, Any]:
    analyze_config, _apply_recommended_config, _apply_tool_preference, _rollback_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, load_config, IndexStore, _read_decisions, summarize_decisions = _load_modules()
    try:
        cfg = load_config()
    except Exception as exc:
        from hermes_tool_slimmer.config import ToolSlimmerConfig

        cfg = ToolSlimmerConfig(enabled=False)
        return {"ok": False, "error": str(exc), "advisor": analyze_config(cfg, summarize_decisions(limit=limit, require_session=True), 0)}
    index = IndexStore().load() or {}
    documents = index.get("documents") if isinstance(index.get("documents"), list) else []
    available = {str(doc.get("name")) for doc in documents if isinstance(doc, dict) and doc.get("name")}
    return {"ok": True, "advisor": analyze_config(cfg, summarize_decisions(limit=limit, require_session=True), _safe_int(index.get("total_tools")), available_tools=available)}


@router.post("/advisor/apply")
async def advisor_apply(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    _analyze_config, apply_recommended_config, _apply_tool_preference, _rollback_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, _load_config, _IndexStore, _read_decisions, _summarize_decisions = _load_modules()
    recommended = (payload or {}).get("recommended_config")
    if recommended is not None and not isinstance(recommended, dict):
        raise HTTPException(status_code=400, detail={"error": "invalid_recommended_config", "message": "recommended_config must be an object."})
    return apply_recommended_config(recommended)


@router.post("/advisor/tool-preference")
async def advisor_tool_preference(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _analyze_config, _apply_recommended_config, apply_tool_preference, _rollback_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, _load_config, _IndexStore, _read_decisions, _summarize_decisions = _load_modules()
    tool = payload.get("tool")
    action = payload.get("action")
    profile = payload.get("profile") or "default"
    if not tool or action not in {"always_include", "always_exclude"}:
        raise HTTPException(status_code=400, detail={"error": "invalid_tool_preference", "message": "Send tool plus action always_include or always_exclude."})
    result = apply_tool_preference(str(tool), str(action), profile=str(profile))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/advisor/rollback")
async def advisor_rollback(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _analyze_config, _apply_recommended_config, _apply_tool_preference, rollback_config, _eval_markdown, _eval_prompts, _privacy_inventory, _run_doctor, _load_config, _IndexStore, _read_decisions, _summarize_decisions = _load_modules()
    backup_path = payload.get("backup_path")
    if not backup_path:
        raise HTTPException(status_code=400, detail={"error": "backup_path_required", "message": "Send backup_path from advisor/apply."})
    result = rollback_config(str(backup_path))
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result)
    return result


@router.get("/privacy")
async def privacy() -> dict[str, Any]:
    _analyze_config, _apply_recommended_config, _apply_tool_preference, _rollback_config, _eval_markdown, _eval_prompts, privacy_inventory, _run_doctor, _load_config, _IndexStore, _read_decisions, _summarize_decisions = _load_modules()
    return {"ok": True, "privacy": privacy_inventory()}


@router.get("/eval-report")
async def eval_report() -> dict[str, Any]:
    _analyze_config, _apply_recommended_config, _apply_tool_preference, _rollback_config, eval_markdown, eval_prompts, _privacy_inventory, _run_doctor, load_config, _IndexStore, _read_decisions, _summarize_decisions = _load_modules()
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
