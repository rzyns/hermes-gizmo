from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any

from .anthropic_tool_search import maybe_anthropic_tools
from .config import ToolSlimmerConfig, load_config
from .corpus import tool_name
from .index_store import IndexStore
from .metrics import record_decision, reduction_metrics
from .selector import ToolSelector
from .session_tools import SessionLoadedState
from .tools import FULL_TOOLS_REQUEST_MARKER
from .types import Schema

LOG = logging.getLogger(__name__)

FALLBACK_INSTRUCTION = (
    "Tool Slimmer may hide tools. If a skill or task requires a missing tool, "
    "call tool_slimmer_request_full_tools; do not invent replacement tools."
)

_TOOL_NAME_RE = re.compile(r"\b[a-z][a-z0-9_]{2,}\b")


def _load_config_for_hook() -> ToolSlimmerConfig:
    try:
        return load_config()
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


def _contains_full_tools_request(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get(FULL_TOOLS_REQUEST_MARKER) is True:
            return True
        return any(_contains_full_tools_request(item) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_full_tools_request(item) for item in value)
    if isinstance(value, str):
        return FULL_TOOLS_REQUEST_MARKER in value
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
        str(schema.get("name") or (schema.get("function") or {}).get("name") or "")
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
        _sync_live_index(
            schemas,
            cfg.min_total_tools,
            {
                "provider": provider,
                "model": model,
                "platform": platform,
                "session_id": session_id,
                "schema_count": len(schemas),
            },
        )
        if _full_tools_requested(conversation_history):
            metrics = reduction_metrics(cfg.mode, schemas, schemas, [])
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
            return None if cfg.dry_run else schemas
        if len(schemas) < cfg.min_total_tools:
            metrics = reduction_metrics(cfg.mode, schemas, schemas, [])
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
            return None

        effective_cfg = cfg
        query = _selection_query(user_message, conversation_history, schemas)
        result = ToolSelector(effective_cfg).select(
            query,
            schemas,
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
            schemas if cfg.mode == "anthropic_tool_search" else result.selected,
            result.selected_names,
            effective_cfg,
            explicit_capability=cfg.anthropic.tool_search_supported,
        )
        if cfg.mode == "anthropic_tool_search" and selected is schemas:
            # Unsupported provider path: fall back to deterministic keyword selection,
            # not the full catalog, unless the user explicitly chose eager mode.
            fallback_cfg = ToolSlimmerConfig.from_mapping(
                {**cfg.__dict__, "mode": "keyword", "anthropic": cfg.anthropic.__dict__}
            )
            result = ToolSelector(fallback_cfg).select(
                query,
                schemas,
                conversation_history=conversation_history,
                model=model,
                platform=platform,
                provider=provider,
                session_id=session_id,
                **kwargs,
            )
            selected = result.selected
            effective_cfg = fallback_cfg
        metrics = _metrics_for_selection(effective_cfg.mode, schemas, selected, result.selected, result.always_included)
        metrics["selection_ms"] = round((perf_counter() - started) * 1000, 3)
        metrics["selected_scores"] = {name: result.score_details.get(name, {}) for name in result.selected_names}
        metrics["top_candidates"] = [
            {"name": name, "score": score, "details": result.score_details.get(name, {})}
            for name, score in sorted(result.scores.items(), key=lambda item: item[1], reverse=True)[:10]
        ]
        metrics["expanded_query_tokens"] = result.expanded_query_tokens
        raw_reduction = metrics["estimated_reduction_percent"]
        reduction_percent = raw_reduction if isinstance(raw_reduction, (int, float)) else 0.0
        if reduction_percent < cfg.min_estimated_reduction_percent:
            selected = schemas
            metrics = reduction_metrics(effective_cfg.mode, schemas, selected, result.always_included)
            metrics["selection_ms"] = round((perf_counter() - started) * 1000, 3)
            metrics["selected_scores"] = {}
            metrics["top_candidates"] = []
            metrics["pre_skip_selected"] = result.selected_names
            metrics["expanded_query_tokens"] = result.expanded_query_tokens
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
        selected = _inject_session_loaded(selected, schemas, cfg, session_id=session_id)
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
    if callable(register_hook):
        try:
            register_hook("pre_llm_call", pre_llm_diagnostic_hook)
        except Exception as exc:  # pragma: no cover - depends on Hermes version
            LOG.warning("pre_llm_call diagnostic hook registration failed: %s", exc)
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
        valid_hooks = _known_valid_hooks(ctx)
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
