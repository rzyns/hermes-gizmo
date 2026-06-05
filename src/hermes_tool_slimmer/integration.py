from __future__ import annotations

import json
import logging
import re
from time import perf_counter
from typing import Any

from .anthropic_tool_search import maybe_anthropic_tools
from .config import ToolSlimmerConfig, load_config
from .corpus import tool_name
from .index_store import IndexStore
from .metrics import record_decision, reduction_metrics
from .native import native_tool_search_active, native_tool_search_bridge_names
from .policy import eligible_schemas
from .schemas import (
    HYDRATE_TOOLS_SCHEMA,
    LOADED_TOOLS_SCHEMA,
    REQUEST_FULL_TOOLS_SCHEMA,
    TOOL_DETAILS_SCHEMA,
    TOOL_SEARCH_SCHEMA,
)
from .selector import ToolSelector
from .session_tools import SessionLoadedState
from .tools import FULL_TOOLS_REQUEST_MARKER
from .two_pass import (
    HYDRATE_TOOL_NAME,
    compact_catalog,
    compact_catalog_metrics,
    hydrate_tool_schema,
    requested_hydration_tools,
)
from .types import Schema, SelectionResult

LOG = logging.getLogger(__name__)

FALLBACK_INSTRUCTION = (
    "Tool Slimmer may hide tools. If a skill or task requires a missing tool, "
    "call tool_slimmer_request_full_tools; do not invent replacement tools."
)

_TOOL_NAME_RE = re.compile(r"\b[a-z][a-z0-9_]{2,}\b")
_HYDRATED_BY_SESSION: dict[str, set[str]] = {}


def _load_config_for_hook() -> ToolSlimmerConfig:
    try:
        return load_config(strict=True)
    except Exception as exc:
        LOG.warning("tool-slimmer config load failed; disabling selector for this request: %s", exc)
        return ToolSlimmerConfig(enabled=False)


def _sync_live_index(schemas: list[Schema], min_total_tools: int, context: dict[str, Any] | None = None) -> None:
    if len(schemas) < min_total_tools:
        return
    try:
        store = IndexStore()
        if context and context.get("session_id"):
            store.save_live_schemas(schemas, context)
        current = store.load() or {}
        current_total = current.get("total_tools")
        if isinstance(current_total, int) and current_total > len(schemas):
            return
        store.ensure(schemas)
    except Exception as exc:
        LOG.warning("tool-slimmer live index sync failed: %s", exc)


def _metrics_for_selection(
    mode: str,
    schemas: list[Schema],
    selected: list[Schema],
    hot_selected: list[Schema],
    always_included: list[str],
) -> dict[str, object]:
    metrics_selected = selected
    if mode == "anthropic_tool_search" and selected is not hot_selected:
        metrics_selected = hot_selected
    metrics = reduction_metrics(mode, schemas, metrics_selected, always_included)
    if mode == "anthropic_tool_search" and selected is not hot_selected:
        metrics["metric_basis"] = "hot_set"
        metrics["anthropic_payload_tools"] = len(selected)
        metrics["anthropic_deferred_tools"] = sum(
            1 for schema in selected if isinstance(schema, dict) and schema.get("defer_loading") is True
        )
    return metrics


def _schema_by_name(schemas: list[Schema]) -> dict[str, Schema]:
    out: dict[str, Schema] = {}
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        name = tool_name(schema)
        if name and name not in out:
            out[name] = schema
    return out


RECOVERY_TOOL_SCHEMAS: tuple[Schema, ...] = (
    REQUEST_FULL_TOOLS_SCHEMA,
    TOOL_SEARCH_SCHEMA,
    TOOL_DETAILS_SCHEMA,
    LOADED_TOOLS_SCHEMA,
    HYDRATE_TOOLS_SCHEMA,
)


def _ensure_recovery_tool_schemas(schemas: list[Schema]) -> tuple[list[Schema], list[str]]:
    """Append Tool Slimmer recovery schemas when upstream toolset filtering hid them.

    ACP and other restricted toolset contexts can invoke this selector hook with
    a catalog that excludes plugin-registered Tool Slimmer tools. Without these
    schemas, active slimming can trap the model in a reduced tool set with no
    recovery/discovery surface. The registry handlers remain globally
    dispatchable; this only restores their request-local model schemas.
    """
    by_name = _schema_by_name(schemas)
    augmented = list(schemas)
    injected: list[str] = []
    for schema in RECOVERY_TOOL_SCHEMAS:
        name = tool_name(schema)
        if name and name not in by_name:
            augmented.append(dict(schema))
            injected.append(name)
    return augmented, injected


def _always_include_schemas(schemas_by_name: dict[str, Schema], cfg: ToolSlimmerConfig) -> tuple[list[Schema], list[str]]:
    selected: list[Schema] = []
    names: list[str] = []
    for name in [*cfg.always_include, "tool_slimmer_request_full_tools", HYDRATE_TOOL_NAME]:
        if name in schemas_by_name and name not in names:
            selected.append(schemas_by_name[name])
            names.append(name)
    return selected, names


def _two_pass_selected_schemas(
    schemas: list[Schema],
    cfg: ToolSlimmerConfig,
    conversation_history: list[Any] | None,
    session_id: str | None,
) -> tuple[list[Schema], dict[str, object], str | None]:
    schemas = eligible_schemas(schemas, cfg)
    schemas_by_name = _schema_by_name(schemas)
    catalog = compact_catalog(schemas, cfg)
    catalog_names = {item.name for item in catalog}
    hydrate_schema = schemas_by_name.get(HYDRATE_TOOL_NAME)
    if hydrate_schema is None:
        if cfg.two_pass.fallback_to_keyword:
            return [], compact_catalog_metrics(catalog, schemas), "missing_hydrate_tool"
        return schemas, compact_catalog_metrics(catalog, schemas), "missing_hydrate_tool_fail_open"

    selected, always_names = _always_include_schemas(schemas_by_name, cfg)
    selected_names = set(always_names)

    requested = [name for name in requested_hydration_tools(conversation_history) if name in schemas_by_name]
    requested = requested[: cfg.two_pass.hydrate_limit]
    cache_key = session_id or ""
    cached = _HYDRATED_BY_SESSION.setdefault(cache_key, set()) if cache_key else set()
    if requested and cfg.two_pass.cache_hydrated_tools and cache_key:
        cached.update(requested)
    hydrated = sorted((cached if cfg.two_pass.cache_hydrated_tools else set()) | set(requested))
    hydrated = [name for name in hydrated if name in schemas_by_name and name in catalog_names]
    hydrated = hydrated[: cfg.two_pass.hydrate_limit]

    for name in hydrated:
        if name not in selected_names:
            selected.append(schemas_by_name[name])
            selected_names.add(name)

    dynamic_hydrate = hydrate_tool_schema(hydrate_schema, catalog)
    selected = [dynamic_hydrate if _tool_schema_name(schema) == HYDRATE_TOOL_NAME else schema for schema in selected]
    metadata = compact_catalog_metrics(catalog, schemas)
    metadata.update(
        {
            "two_pass_requested_tools": requested,
            "two_pass_hydrated_tools": hydrated,
            "two_pass_cached_tools": sorted(cached) if cfg.two_pass.cache_hydrated_tools else [],
            "two_pass_cache_scope": "session" if cache_key and cfg.two_pass.cache_hydrated_tools else "request",
            "two_pass_phase": "hydrate" if hydrated else "catalog",
        }
    )
    return selected, metadata, None


def _tool_schema_name(schema: Schema) -> str:
    function = schema.get("function") if isinstance(schema, dict) else {}
    return str(schema.get("name") or (function.get("name") if isinstance(function, dict) else "") or "")


def _contains_full_tools_request(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("role") != "tool":
        return False
    content = value.get("content")
    if isinstance(content, dict):
        return content.get(FULL_TOOLS_REQUEST_MARKER) is True
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return False
        return isinstance(payload, dict) and payload.get(FULL_TOOLS_REQUEST_MARKER) is True
    return False


def _full_tools_requested(conversation_history: list[Any] | None) -> bool:
    history = conversation_history or []
    last_marker_index: int | None = None
    for index, item in enumerate(history):
        if _contains_full_tools_request(item):
            last_marker_index = index
    if last_marker_index is None:
        return False

    # Keep full tools through the current tool-call chain and the first user
    # retry after the marker. Some models call the fallback, then answer with
    # "send anything again" instead of immediately retrying the task. Expiring
    # at the first user message recreates the same missing-tool loop.
    user_messages_after_marker = sum(
        1
        for item in history[last_marker_index + 1 :]
        if isinstance(item, dict) and item.get("role") == "user"
    )
    if user_messages_after_marker <= 1:
        return True
    return False


def _text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_text_content(item) for item in value.values())
    if isinstance(value, list | tuple):
        return " ".join(_text_content(item) for item in value)
    return ""


def _recent_tool_mentions(conversation_history: list[Any] | None, schemas: list[Schema]) -> list[str]:
    known_names = {
        _tool_schema_name(schema)
        for schema in schemas
        if isinstance(schema, dict)
    }
    known_names.discard("")
    if not known_names:
        return []

    history = conversation_history or []
    # conversation_history already includes the current user message in Hermes.
    # Look at assistant/tool context immediately before that current user turn.
    index = len(history) - 1
    if index >= 0 and isinstance(history[index], dict) and history[index].get("role") == "user":
        index -= 1

    mentioned: list[str] = []
    seen: set[str] = set()
    while index >= 0:
        item = history[index]
        if isinstance(item, dict) and item.get("role") == "user":
            break
        text = _text_content(item)
        for token in _TOOL_NAME_RE.findall(text):
            if token in known_names and token not in seen:
                mentioned.append(token)
                seen.add(token)
        index -= 1
    return mentioned


def _selection_query(user_message: str, conversation_history: list[Any] | None, schemas: list[Schema]) -> str:
    mentions = _recent_tool_mentions(conversation_history, schemas)
    if not mentions:
        return user_message
    return f"{user_message}\n\nRecent missing/needed tool mentions: {' '.join(mentions)}"


def select_tool_schemas_callback(
    user_message: str,
    conversation_history: list[Any] | None,
    schemas: list[Schema],
    model: str,
    platform: str,
    provider: str | None = None,
    session_id: str | None = None,
    config: ToolSlimmerConfig | None = None,
    **kwargs: Any,
) -> list[Schema] | None:
    cfg = config or _load_config_for_hook()
    cfg = cfg.for_context(platform=platform)
    if not cfg.enabled:
        return None
    try:
        started = perf_counter()
        upstream_schema_count = len(schemas)
        recovery_meta_injected: list[str] = []
        if str(platform or "").strip().lower() == "acp":
            schemas, recovery_meta_injected = _ensure_recovery_tool_schemas(schemas)
        _sync_live_index(
            schemas,
            cfg.min_total_tools,
            {
                "provider": provider,
                "model": model,
                "platform": platform,
                "session_id": session_id,
                "schema_count": len(schemas),
                "upstream_schema_count": upstream_schema_count,
                "recovery_meta_injected": recovery_meta_injected,
            },
        )
        if native_tool_search_active(schemas):
            bridge_tools = native_tool_search_bridge_names(schemas)
            metrics = reduction_metrics(cfg.mode, schemas, schemas, [])
            metrics["selection_ms"] = round((perf_counter() - started) * 1000, 3)
            metrics["skipped"] = True
            metrics["skip_reason"] = "native_hermes_tool_search_active"
            metrics["native_hermes_tool_search"] = True
            metrics["native_hermes_bridge_tools"] = bridge_tools
            if cfg.log_decisions:
                LOG.info("tool-slimmer skipped; Hermes native Tool Search is active", extra={"tool_slimmer": metrics})
                try:
                    record_decision(
                        metrics,
                        {
                            "provider": provider,
                            "model": model,
                            "platform": platform,
                            "session_id": session_id,
                            "dry_run": cfg.dry_run,
                            "schema_count": len(schemas),
                        },
                    )
                except Exception as exc:
                    LOG.warning("tool-slimmer decision logging failed: %s", exc)
            return None
        policy_schemas = eligible_schemas(schemas, cfg)
        if _full_tools_requested(conversation_history):
            metrics = reduction_metrics(cfg.mode, schemas, policy_schemas, [])
            metrics["selection_ms"] = round((perf_counter() - started) * 1000, 3)
            metrics["skipped"] = True
            metrics["skip_reason"] = "full_tools_requested"
            if cfg.log_decisions:
                LOG.info("tool-slimmer full schema fallback", extra={"tool_slimmer": metrics})
                try:
                    record_decision(
                        metrics,
                        {
                            "provider": provider,
                            "model": model,
                            "platform": platform,
                            "session_id": session_id,
                            "dry_run": cfg.dry_run,
                            "schema_count": len(schemas),
                        },
                    )
                except Exception as exc:
                    LOG.warning("tool-slimmer decision logging failed: %s", exc)
            return None if cfg.dry_run else policy_schemas
        if len(schemas) < cfg.min_total_tools:
            metrics = reduction_metrics(cfg.mode, schemas, policy_schemas, [])
            metrics["selection_ms"] = round((perf_counter() - started) * 1000, 3)
            metrics["skipped"] = True
            metrics["skip_reason"] = "below_min_total_tools"
            metrics["min_total_tools"] = cfg.min_total_tools
            if cfg.log_decisions:
                LOG.info("tool-slimmer skipped", extra={"tool_slimmer": metrics})
                try:
                    record_decision(
                        metrics,
                        {
                            "provider": provider,
                            "model": model,
                            "platform": platform,
                            "session_id": session_id,
                            "dry_run": cfg.dry_run,
                            "schema_count": len(schemas),
                        },
                    )
                except Exception as exc:
                    LOG.warning("tool-slimmer decision logging failed: %s", exc)
            if cfg.dry_run or len(policy_schemas) == len(schemas):
                return None
            return policy_schemas

        effective_cfg = cfg
        query = _selection_query(user_message, conversation_history, policy_schemas)
        if cfg.mode == "two_pass":
            selected, two_pass_metrics, two_pass_fallback = _two_pass_selected_schemas(
                policy_schemas,
                cfg,
                conversation_history,
                session_id,
            )
            if two_pass_fallback == "missing_hydrate_tool" and cfg.two_pass.fallback_to_keyword:
                fallback_cfg = ToolSlimmerConfig.from_mapping(
                    {**cfg.__dict__, "mode": "keyword", "anthropic": cfg.anthropic.__dict__, "two_pass": cfg.two_pass.__dict__}
                )
                result = ToolSelector(fallback_cfg).select(
                    query,
                    policy_schemas,
                    conversation_history=conversation_history,
                    model=model,
                    platform=platform,
                    provider=provider,
                    session_id=session_id,
                    **kwargs,
                )
                selected = result.selected
                effective_cfg = fallback_cfg
                two_pass_metrics["two_pass_fallback"] = two_pass_fallback
            else:
                selected_names = [_tool_schema_name(schema) for schema in selected]
                selected_name_set = set(selected_names)
                result = SelectionResult(
                    mode=cfg.mode,
                    selected=selected,
                    selected_names=selected_names,
                    scores={},
                    total_tools=len(schemas),
                    always_included=[
                        name for name in [*cfg.always_include, "tool_slimmer_request_full_tools", HYDRATE_TOOL_NAME]
                        if name in selected_name_set
                    ],
                    reason=two_pass_fallback,
                    metadata=two_pass_metrics,
                )
        else:
            result = ToolSelector(effective_cfg).select(
                query,
                policy_schemas,
                conversation_history=conversation_history,
                model=model,
                platform=platform,
                provider=provider,
                session_id=session_id,
                **kwargs,
            )
            selected = maybe_anthropic_tools(
                provider,
                model,
                policy_schemas if cfg.mode == "anthropic_tool_search" else result.selected,
                result.selected_names,
                effective_cfg,
                explicit_capability=cfg.anthropic.tool_search_supported,
            )
        if cfg.mode == "anthropic_tool_search" and selected is policy_schemas:
            # Unsupported provider path: fall back to deterministic keyword selection,
            # not the full catalog, unless the user explicitly chose eager mode.
            fallback_cfg = ToolSlimmerConfig.from_mapping(
                {**cfg.__dict__, "mode": "keyword", "anthropic": cfg.anthropic.__dict__, "two_pass": cfg.two_pass.__dict__}
            )
            result = ToolSelector(fallback_cfg).select(
                query,
                policy_schemas,
                conversation_history=conversation_history,
                model=model,
                platform=platform,
                provider=provider,
                session_id=session_id,
                **kwargs,
            )
            selected = result.selected
            effective_cfg = fallback_cfg
        selected_before_session_load = selected
        selected = _inject_session_loaded(selected, schemas, cfg, session_id=session_id)
        if selected is not selected_before_session_load:
            before_names = {tool_name(s) for s in selected_before_session_load if isinstance(s, dict)}
            injected_names = [tool_name(s) for s in selected if isinstance(s, dict) and tool_name(s) not in before_names]
        else:
            injected_names = []
        metrics = _metrics_for_selection(effective_cfg.mode, schemas, selected, result.selected, result.always_included)
        if injected_names:
            metrics["session_loaded_injected"] = injected_names
        if result.metadata:
            metrics.update(result.metadata)
        if recovery_meta_injected:
            metrics["recovery_meta_injected"] = recovery_meta_injected
            metrics["upstream_schema_count"] = upstream_schema_count
        metrics["selection_ms"] = round((perf_counter() - started) * 1000, 3)
        metrics["selected_scores"] = {name: result.score_details.get(name, {}) for name in result.selected_names}
        metrics["top_candidates"] = [
            {"name": name, "score": score, "details": result.score_details.get(name, {})}
            for name, score in sorted(result.scores.items(), key=lambda item: item[1], reverse=True)[:10]
        ]
        metrics["expanded_query_token_count"] = len(result.expanded_query_tokens)
        raw_reduction = metrics["estimated_reduction_percent"]
        reduction_percent = raw_reduction if isinstance(raw_reduction, (int, float)) else 0.0
        if effective_cfg.mode != "two_pass" and reduction_percent < cfg.min_estimated_reduction_percent:
            selected = policy_schemas
            metrics = reduction_metrics(effective_cfg.mode, schemas, selected, result.always_included)
            metrics["selection_ms"] = round((perf_counter() - started) * 1000, 3)
            metrics["selected_scores"] = {}
            metrics["top_candidates"] = []
            metrics["pre_skip_selected"] = result.selected_names
            metrics["expanded_query_token_count"] = len(result.expanded_query_tokens)
            metrics["skipped"] = True
            metrics["skip_reason"] = "below_min_estimated_reduction_percent"
            metrics["min_estimated_reduction_percent"] = cfg.min_estimated_reduction_percent
        if cfg.log_decisions:
            LOG.info("tool-slimmer selection", extra={"tool_slimmer": metrics})
            try:
                record_decision(
                    metrics,
                    {
                        "provider": provider,
                        "model": model,
                        "platform": platform,
                        "session_id": session_id,
                        "dry_run": cfg.dry_run,
                        "schema_count": len(schemas),
                    },
                )
            except Exception as exc:
                LOG.warning("tool-slimmer decision logging failed: %s", exc)
        if cfg.dry_run:
            return None
        return selected
    except Exception:
        LOG.exception("tool-slimmer selector failed; using original schemas")
        if cfg.fail_open:
            return None
        raise


def pre_llm_diagnostic_hook(**kwargs: Any) -> dict[str, str] | None:
    cfg = _load_config_for_hook()
    if not cfg.enabled:
        return None
    if not cfg.dry_run:
        return {"context": FALLBACK_INSTRUCTION}
    return {
        "context": (
            f"{FALLBACK_INSTRUCTION} "
            "Hermes Tool Slimmer dry-run is enabled; "
            "schema selection is diagnostic-only for this turn."
        )
    }


SESSION_BRIDGE_TOOL_DETAILS_NAMES = {"tool_slimmer_tool_details", "gizmo_tool_details"}
SESSION_BRIDGE_LOADED_TOOLS_NAMES = {"tool_slimmer_loaded_tools", "gizmo_loaded_tools"}


def _sync_session_loaded_from_tool_result(
    *,
    tool_name: str,
    args: Any,
    result: Any,
    session_id: str | None,
) -> None:
    """Bridge progressive load/unload tool calls into the active Hermes session.

    Hermes core passes session_id to hooks, but not to registry.dispatch handlers.
    The details handler therefore updates the anonymous registry during the tool
    call itself. This hook mirrors successful load/unload actions from both the
    legacy Tool Slimmer name and the Gizmo alias into the real session so the next
    select_tool_schemas hook can inject loaded tools.
    """
    if tool_name not in SESSION_BRIDGE_TOOL_DETAILS_NAMES or not session_id:
        return
    raw_args = args if isinstance(args, dict) else {}
    try:
        payload = json.loads(result) if isinstance(result, str) else result
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return

    name = str(payload.get("name") or raw_args.get("name") or "").strip()
    if not name:
        return

    try:
        cfg = load_config(raw_args.get("config_path") if isinstance(raw_args, dict) else None)
        cfg = cfg.for_context(platform=raw_args.get("platform"), profile=raw_args.get("profile"))
    except Exception as exc:
        LOG.debug("tool-slimmer session bridge config load failed: %s", exc)
        return
    if not cfg.progressive_enabled:
        return

    state = SessionLoadedState(
        max_loaded=cfg.progressive_max_loaded,
        ttl_seconds=cfg.progressive_ttl_seconds,
        session_id=session_id,
    )
    if payload.get("load_action") == "added":
        info_raw = payload.get("info")
        info = info_raw if isinstance(info_raw, dict) else {}
        state.add(name, toolset=info.get("toolset"))
    elif payload.get("unload_action") == "removed":
        state.remove(name)


def post_tool_call_session_bridge_hook(**kwargs: Any) -> None:
    """Post-tool hook wrapper for mirroring progressive loads to session state."""
    _sync_session_loaded_from_tool_result(
        tool_name=str(kwargs.get("tool_name") or ""),
        args=kwargs.get("args"),
        result=kwargs.get("result"),
        session_id=str(kwargs.get("session_id") or "") or None,
    )
    return None


def transform_loaded_tools_session_bridge_hook(**kwargs: Any) -> str | None:
    """Return loaded-tools diagnostics for the active session when core supplies it."""
    if kwargs.get("tool_name") not in SESSION_BRIDGE_LOADED_TOOLS_NAMES:
        return None
    session_id = str(kwargs.get("session_id") or "").strip()
    if not session_id:
        return None
    from .session_tools import tool_slimmer_loaded_tools

    args_raw = kwargs.get("args")
    args = args_raw if isinstance(args_raw, dict) else {}
    bridged_args = {**args, "session_id": session_id}
    return tool_slimmer_loaded_tools(bridged_args)


def _inject_session_loaded(selected: list[Schema], full_schemas: list[Schema], cfg: ToolSlimmerConfig, session_id: str | None = None) -> list[Schema]:
    """Merge session-loaded tools into the selected set, excluding disabled ones."""
    if not cfg.progressive_enabled:
        return selected
    state = SessionLoadedState(
        max_loaded=cfg.progressive_max_loaded,
        ttl_seconds=cfg.progressive_ttl_seconds,
        session_id=session_id,
    )
    loaded = state.loaded_names()
    if not loaded:
        return selected

    from .session_tools import _schema_is_eligible

    full_names = {tool_name(s): s for s in full_schemas if isinstance(s, dict)}
    selected_names = {tool_name(s) for s in selected if isinstance(s, dict)}

    to_add: list[Schema] = []
    for name in loaded:
        schema = full_names.get(name)
        if schema is None:
            continue
        if not _schema_is_eligible(schema, cfg):
            continue
        if name in selected_names:
            continue
        to_add.append(schema)

    if not to_add:
        return selected
    return [*selected, *to_add]


def _known_valid_hooks(ctx: Any) -> set[str] | None:
    valid_hooks = getattr(ctx, "valid_hooks", None) or getattr(ctx, "VALID_HOOKS", None)
    manager = getattr(ctx, "_manager", None)
    if valid_hooks is None and manager is not None:
        valid_hooks = getattr(manager, "VALID_HOOKS", None) or getattr(manager, "valid_hooks", None)
    if valid_hooks is None:
        try:
            from hermes_cli.plugins import VALID_HOOKS  # type: ignore[import-not-found]
        except Exception:
            return None
        valid_hooks = VALID_HOOKS
    try:
        return {str(hook) for hook in valid_hooks}
    except TypeError:
        return None


def maybe_register_selector_hook(ctx: Any) -> bool:
    """Register the selector with Hermes if a selector hook surface exists.

    Returns True when a known registration method accepted the callback. This
    avoids monkeypatching: unsupported Hermes versions keep diagnostics/CLI only.
    """
    selector_registered = False
    register_hook = getattr(ctx, "register_hook", None)
    valid_hooks = _known_valid_hooks(ctx) if callable(register_hook) else None

    def hook_available(name: str) -> bool:
        return valid_hooks is None or name in valid_hooks

    if callable(register_hook):
        if hook_available("pre_llm_call"):
            try:
                register_hook("pre_llm_call", pre_llm_diagnostic_hook)
            except Exception as exc:  # pragma: no cover - depends on Hermes version
                LOG.warning("pre_llm_call diagnostic hook registration failed: %s", exc)
        if hook_available("post_tool_call"):
            try:
                register_hook("post_tool_call", post_tool_call_session_bridge_hook)
            except Exception as exc:  # pragma: no cover - depends on Hermes version
                LOG.warning("post_tool_call session bridge hook registration failed: %s", exc)
        if hook_available("transform_tool_result"):
            try:
                register_hook("transform_tool_result", transform_loaded_tools_session_bridge_hook)
            except Exception as exc:  # pragma: no cover - depends on Hermes version
                LOG.warning("transform_tool_result session bridge hook registration failed: %s", exc)
    callback = select_tool_schemas_callback
    for method_name in ("register_tool_schema_selector", "register_schema_selector"):
        method = getattr(ctx, method_name, None)
        if callable(method):
            try:
                method(callback)
                return True
            except Exception as exc:
                LOG.warning("%s registration failed: %s", method_name, exc)
    if callable(register_hook):
        if valid_hooks is not None and "select_tool_schemas" not in valid_hooks:
            LOG.warning("Hermes selector hook is unavailable; tool-slimmer will run diagnostics only")
            return False
        try:
            register_hook("select_tool_schemas", callback)
            selector_registered = True
        except Exception as exc:
            LOG.warning("select_tool_schemas hook registration failed: %s", exc)
    if not selector_registered:
        LOG.warning("Hermes selector hook is unavailable; tool-slimmer will run diagnostics only")
    return selector_registered
