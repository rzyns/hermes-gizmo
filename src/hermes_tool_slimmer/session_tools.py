from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ToolSlimmerConfig, hermes_home, load_config
from .bm25 import BM25
from .corpus import build_corpus, tool_description, tool_name, tool_toolset
from .tokenizer import tokenize
from .toolsets import is_mcp_schema
from .tools import _json, _resolve_schemas
from .private_io import write_private_json
from .types import Schema

LOG = logging.getLogger(__name__)


@dataclass
class LoadedToolInfo:
    """Metadata for a single tool held in session-loaded state."""

    name: str
    loaded_at: float
    expires_at: float | None
    last_used_at: float = 0.0
    use_count: int = 0
    toolset: str | None = None


class SessionLoadedState:
    """File-backed session-loaded tool registry with per-session isolation, TTL, and LRU eviction."""

    def __init__(
        self,
        path: Path | str | None = None,
        max_loaded: int = 20,
        ttl_seconds: int = 3600,
        session_id: str | None = None,
    ) -> None:
        self.state_path = (
            Path(path or hermes_home() / "tool-slimmer" / "session_loaded.json")
            .expanduser()
        )
        self.max_loaded = max_loaded
        self.ttl_seconds = ttl_seconds
        self.session_id = session_id or "__anonymous__"
        self._infos: dict[str, LoadedToolInfo] = {}
        self._load()

    def _load(self) -> None:
        data: dict[str, Any] | None = None
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())  # type: ignore[assignment]
            except json.JSONDecodeError:
                pass
        if not isinstance(data, dict):
            data = {}
        version = data.get("version")
        raw_tools: dict[str, Any] = {}
        if version == 2:
            sessions = data.get("sessions", {})
            if isinstance(sessions, dict):
                session_data = sessions.get(self.session_id, {})
                if isinstance(session_data, dict):
                    raw_tools = session_data.get("loaded_tools", {})
        elif isinstance(data.get("loaded_tools"), dict):
            # Legacy v1: migrate only for the anonymous session
            if self.session_id == "__anonymous__":
                raw_tools = data["loaded_tools"]
                LOG.debug("Migrated legacy session-loaded state to anonymous session")
        if not isinstance(raw_tools, dict):
            raw_tools = {}
        self._infos = {}
        for name, entry in raw_tools.items():
            if isinstance(entry, dict):
                loaded_at = float(entry.get("loaded_at", 0))
                expires_raw = entry.get("expires_at")
                expires_at = float(expires_raw) if expires_raw is not None else None
                self._infos[str(name)] = LoadedToolInfo(
                    name=str(name),
                    loaded_at=loaded_at,
                    expires_at=expires_at,
                    last_used_at=float(entry.get("last_used_at", loaded_at)),
                    use_count=int(entry.get("use_count", 0)),
                    toolset=entry.get("toolset") if entry.get("toolset") is not None else None,
                )
        self.evict_expired()

    def _save(self) -> None:
        # Preserve other sessions when writing
        all_sessions: dict[str, Any] = {}
        if self.state_path.exists():
            try:
                existing = json.loads(self.state_path.read_text())
                if isinstance(existing, dict) and existing.get("version") == 2:
                    existing_sessions = existing.get("sessions", {})
                    if isinstance(existing_sessions, dict):
                        all_sessions = existing_sessions
            except (OSError, json.JSONDecodeError):
                pass

        payload_tools = {
            info.name: {
                "loaded_at": info.loaded_at,
                "expires_at": info.expires_at,
                "last_used_at": info.last_used_at,
                "use_count": info.use_count,
                "toolset": info.toolset,
            }
            for info in self._infos.values()
        }
        all_sessions[self.session_id] = {"loaded_tools": payload_tools}

        payload = {
            "version": 2,
            "sessions": all_sessions,
            "updated_at": time.time(),
        }
        write_private_json(self.state_path, payload, indent=2, sort_keys=True)

    def evict_expired(self) -> list[str]:
        """Remove expired entries and save. Returns evicted names."""
        now = time.time()
        expired = [name for name, info in self._infos.items() if info.expires_at is not None and info.expires_at <= now]
        for name in expired:
            del self._infos[name]
        if expired:
            self._save()
        return expired

    def evict_lru_if_needed(self) -> list[str]:
        """Remove least-recently-used entries while over max_loaded. Returns evicted names."""
        if len(self._infos) <= self.max_loaded:
            return []
        sorted_by_lru = sorted(self._infos.values(), key=lambda i: (i.last_used_at, i.loaded_at))
        to_evict = sorted_by_lru[: len(self._infos) - self.max_loaded]
        removed: list[str] = []
        for info in to_evict:
            del self._infos[info.name]
            removed.append(info.name)
        if removed:
            self._save()
        return removed

    def add(self, name: str, *, toolset: str | None = None) -> bool:
        """Load a tool into the session state. Returns True if newly added or updated."""
        now = time.time()
        expires = (now + self.ttl_seconds) if self.ttl_seconds > 0 else None
        existing = self._infos.get(name)
        if existing is not None:
            self._infos[name] = LoadedToolInfo(
                name=name,
                loaded_at=now,
                expires_at=expires,
                last_used_at=now,
                use_count=existing.use_count + 1,
                toolset=toolset or existing.toolset,
            )
        else:
            self._infos[name] = LoadedToolInfo(
                name=name,
                loaded_at=now,
                expires_at=expires,
                last_used_at=now,
                use_count=1,
                toolset=toolset,
            )
        self.evict_lru_if_needed()
        self._save()
        return True

    def remove(self, name: str) -> bool:
        """Unload a tool from the session state."""
        if name in self._infos:
            del self._infos[name]
            self._save()
            return True
        return False

    def is_loaded(self, name: str) -> bool:
        """Check whether a tool name is currently loaded (and not expired). Updates LRU."""
        self.evict_expired()
        info = self._infos.get(name)
        if info is None:
            return False
        info.last_used_at = time.time()
        info.use_count += 1
        self._save()
        return True

    def loaded_names(self) -> list[str]:
        """Return currently loaded tool names (after evicting expired)."""
        self.evict_expired()
        return list(self._infos.keys())

    def info_dict(self) -> dict[str, dict[str, Any]]:
        """Return serializable metadata for all loaded tools."""
        self.evict_expired()
        now = time.time()
        return {
            info.name: {
                "loaded_at": info.loaded_at,
                "expires_at": info.expires_at,
                "last_used_at": info.last_used_at,
                "use_count": info.use_count,
                "toolset": info.toolset,
                "seconds_remaining": (
                    max(0.0, info.expires_at - now) if info.expires_at is not None else None
                ),
            }
            for info in self._infos.values()
        }

    def clear(self) -> None:
        """Unload all tools."""
        self._infos.clear()
        self._save()


def _schema_is_eligible(schema: Schema, cfg: ToolSlimmerConfig) -> bool:
    """Return True if a tool schema is eligible (not disabled/excluded by config)."""
    if not isinstance(schema, dict):
        return False
    name = tool_name(schema)
    toolset = tool_toolset(schema)
    if name in cfg.disabled_tools:
        return False
    if toolset and toolset in cfg.disabled_toolsets:
        return False
    is_mcp = is_mcp_schema(schema)
    if is_mcp and not cfg.include_mcp_tools:
        return False
    if not is_mcp and not cfg.include_native_tools:
        return False
    return True


def _is_disabled_or_excluded(name: str, cfg: ToolSlimmerConfig) -> bool:
    """Backward-compatible name-only check.

    **Deprecated**: use `_schema_is_eligible` which also validates toolset,
    MCP/native inclusion, and duplicate-name ambiguity.
    """
    if name in cfg.disabled_tools:
        return True
    return False


def _build_search_documents(schemas: list[Schema]) -> tuple[list[Any], dict[str, Schema], list[str]]:
    """Build BM25-searchable documents, a name->schema lookup, and duplicate names."""
    docs = build_corpus(schemas)
    by_name: dict[str, Schema] = {}
    duplicate_names: list[str] = []
    for schema in schemas:
        n = tool_name(schema)
        if not n:
            continue
        if n in by_name:
            duplicate_names.append(n)
            continue
        by_name[n] = schema
    if duplicate_names:
        LOG.warning(
            "duplicate tool schema names encountered; first schema wins: %s",
            ", ".join(sorted(set(duplicate_names))),
        )
    return docs, by_name, sorted(set(duplicate_names))


def _score_search(query: str, docs: list[Any]) -> dict[str, float]:
    """BM25-based search scoring. Returns {tool_name: score}."""
    if not query.strip():
        return {}
    tokens = tokenize(query)
    if not tokens:
        return {}
    bm25 = BM25([doc.tokens for doc in docs])
    raw_scores = bm25.scores(tokens)
    return {doc.name: raw_scores[i] for i, doc in enumerate(docs) if raw_scores[i] > 0}


def _build_tool_info(schema: Schema) -> dict[str, Any]:
    """Minimal human-readable description of a tool."""
    return {
        "name": tool_name(schema),
        "description": tool_description(schema),
        "toolset": tool_toolset(schema),
    }


def _get_session_id(args: dict[str, Any], kwargs: dict[str, Any]) -> str | None:
    if isinstance(args, dict):
        return args.get("session_id") or kwargs.get("session_id")
    return kwargs.get("session_id")


def _resolve_session_tool_schemas(args: dict[str, Any], kwargs: dict[str, Any]) -> tuple[list[Schema], str]:
    """Resolve schemas for session-management tools.

    Unlike the model-facing selector, these diagnostic/progressive-loading tools are
    supposed to search the live/snapshot catalog when no explicit schemas were
    supplied. Preserve explicit empty `schemas=[]` as a real empty input for tests
    and callers that want to avoid fallback.
    """
    has_explicit_schemas = (isinstance(args, dict) and "schemas" in args) or "schemas" in kwargs
    if has_explicit_schemas:
        return _resolve_schemas(args, kwargs)
    fallback_args = {**args, "allow_catalog_fallback": True}
    return _resolve_schemas(fallback_args, kwargs)


def tool_slimmer_tool_search(args: dict, **kwargs: Any) -> str:
    """Search available tools by query and return ranked, loadable results."""
    try:
        query = str(args.get("query", "")).strip()
        schemas, schema_source = _resolve_session_tool_schemas(args, kwargs)
        if not schemas:
            return _json({
                "ok": False,
                "error": "no_schemas_available",
                "message": "Provide schemas, run inside Hermes with live tool definitions, or rebuild the Tool Slimmer index.",
            })

        cfg = load_config(args.get("config_path") if isinstance(args, dict) else None)
        cfg = cfg.for_context(platform=args.get("platform"), profile=args.get("profile"))

        docs, by_name, duplicate_names = _build_search_documents(schemas)
        duplicate_set = set(duplicate_names)

        scores = _score_search(query, docs)

        # Assemble results: start with scored matches, then append unscored in name order
        result_items: list[dict[str, Any]] = []
        seen: set[str] = set()

        session_id = _get_session_id(args, kwargs)
        state: SessionLoadedState | None = None
        if cfg.progressive_enabled:
            state = SessionLoadedState(
                max_loaded=cfg.progressive_max_loaded,
                ttl_seconds=cfg.progressive_ttl_seconds,
                session_id=session_id,
            )

        # BM25-ranked results
        for name, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            seen.add(name)
            schema = by_name.get(name)
            if schema is None:
                continue
            eligible = _schema_is_eligible(schema, cfg)
            ambiguous = name in duplicate_set
            item: dict[str, Any] = {
                "name": name,
                "score": round(score, 6),
                "info": _build_tool_info(schema),
                "disabled": not eligible,
                "can_load": eligible and not ambiguous,
                "ambiguous": ambiguous,
            }
            if state is not None:
                item["loaded"] = state.is_loaded(name)
            result_items.append(item)

        # Append remaining tools alphabetically (score None)
        for name in sorted(by_name):
            if name in seen:
                continue
            schema = by_name[name]
            eligible = _schema_is_eligible(schema, cfg)
            ambiguous = name in duplicate_set
            item = {
                "name": name,
                "score": None,
                "info": _build_tool_info(schema),
                "disabled": not eligible,
                "can_load": eligible and not ambiguous,
                "ambiguous": ambiguous,
            }
            if state is not None:
                item["loaded"] = state.is_loaded(name)
            result_items.append(item)

        payload: dict[str, Any] = {
            "ok": True,
            "query": query,
            "schema_source": schema_source,
            "total": len(result_items),
            "results": result_items,
            "session_loaded_count": 0,
        }
        if state is not None:
            payload["session_loaded_count"] = len(state.loaded_names())

        return _json(payload)
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def tool_slimmer_tool_details(args: dict, **kwargs: Any) -> str:
    """Return detailed information about a named tool and optionally load it into session."""
    try:
        name = str(args.get("name", "")).strip()
        do_load = bool(args.get("load", False))
        do_unload = bool(args.get("unload", False))
        schemas, schema_source = _resolve_session_tool_schemas(args, kwargs)
        if not schemas:
            return _json({
                "ok": False,
                "error": "no_schemas_available",
                "message": "Provide schemas, run inside Hermes with live tool definitions, or rebuild the Tool Slimmer index.",
            })

        # Build name->schema with duplicate detection
        by_name: dict[str, Schema] = {}
        duplicate_names: set[str] = set()
        for s in schemas:
            n = tool_name(s)
            if not n:
                continue
            if n in by_name:
                duplicate_names.add(n)
            else:
                by_name[n] = s

        if name not in by_name:
            return _json({"ok": False, "error": "tool_not_found", "name": name})

        cfg = load_config(args.get("config_path") if isinstance(args, dict) else None)
        cfg = cfg.for_context(platform=args.get("platform"), profile=args.get("profile"))

        schema = by_name[name]
        eligible = _schema_is_eligible(schema, cfg)
        ambiguous = name in duplicate_names
        disabled = not eligible or ambiguous
        info = _build_tool_info(schema)
        payload: dict[str, Any] = {
            "ok": True,
            "name": name,
            "schema": schema,
            "info": info,
            "disabled": disabled,
            "can_load": not disabled,
            "schema_source": schema_source,
            "ambiguous": ambiguous,
        }

        session_id = _get_session_id(args, kwargs)
        state: SessionLoadedState | None = None
        if cfg.progressive_enabled:
            state = SessionLoadedState(
                max_loaded=cfg.progressive_max_loaded,
                ttl_seconds=cfg.progressive_ttl_seconds,
                session_id=session_id,
            )
            payload["loaded"] = state.is_loaded(name)
        else:
            payload["loaded"] = False

        if do_load:
            if disabled:
                error_code = "tool_ambiguous" if ambiguous else "tool_disabled"
                message = (
                    f"Tool {name!r} has ambiguous duplicate schemas and cannot be loaded."
                    if ambiguous else
                    f"Tool {name!r} is disabled or excluded and cannot be loaded."
                )
                return _json({
                    "ok": False,
                    "error": error_code,
                    "name": name,
                    "message": message,
                })
            if state is None:
                return _json({
                    "ok": False,
                    "error": "progressive_disabled",
                    "message": "Progressive loading is not enabled in config.",
                })
            state.add(name, toolset=info.get("toolset"))
            payload["loaded"] = True
            payload["load_action"] = "added"
        elif do_unload:
            if state is not None:
                removed = state.remove(name)
                payload["loaded"] = state.is_loaded(name)
                payload["unload_action"] = "removed" if removed else "not_loaded"

        return _json(payload)
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def tool_slimmer_loaded_tools(args: dict, **kwargs: Any) -> str:
    """Diagnostic returning the current session-loaded tool registry."""
    try:
        cfg = load_config(args.get("config_path") if isinstance(args, dict) else None)
        cfg = cfg.for_context(platform=args.get("platform"), profile=args.get("profile"))
        session_id = _get_session_id(args, kwargs)
        state = SessionLoadedState(
            max_loaded=cfg.progressive_max_loaded,
            ttl_seconds=cfg.progressive_ttl_seconds,
            session_id=session_id,
        )
        info = state.info_dict()
        return _json({
            "ok": True,
            "progressive_enabled": cfg.progressive_enabled,
            "max_loaded": cfg.progressive_max_loaded,
            "ttl_seconds": cfg.progressive_ttl_seconds,
            "session_id": session_id,
            "count": len(info),
            "tools": info,
        })
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})
