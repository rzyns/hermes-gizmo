from __future__ import annotations

import logging
from typing import Any

from .anthropic_tool_search import maybe_anthropic_tools
from .config import ToolSlimmerConfig, load_config
from .metrics import record_decision, reduction_metrics
from .selector import ToolSelector
from .types import Schema

LOG = logging.getLogger(__name__)


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
    cfg = config or load_config()
    if not cfg.enabled:
        return None
    try:
        effective_cfg = cfg
        result = ToolSelector(effective_cfg).select(
            user_message,
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
                user_message,
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
        metrics = reduction_metrics(effective_cfg.mode, schemas, selected, result.always_included)
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
    cfg = load_config()
    if not cfg.enabled or not cfg.dry_run:
        return None
    return {
        "context": (
            "Hermes Tool Slimmer dry-run is enabled; "
            "schema selection is diagnostic-only for this turn."
        )
    }


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
        valid_hooks = getattr(ctx, "valid_hooks", None) or getattr(ctx, "VALID_HOOKS", None)
        manager = getattr(ctx, "_manager", None)
        if valid_hooks is None and manager is not None:
            valid_hooks = getattr(manager, "VALID_HOOKS", None) or getattr(manager, "valid_hooks", None)
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
