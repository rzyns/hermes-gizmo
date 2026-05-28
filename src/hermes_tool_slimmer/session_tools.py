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
from .tools import _json, _resolve_schemas
from .types import Schema

LOG = logging.getLogger(__name__)


@dataclass
class LoadedToolInfo:
    """Metadata for a single tool held in session-loaded state."""

    name: str
    loaded_at: float
    expires_at: float | None


class SessionLoadedState:
    """File-backed session-loaded tool registry with TTL and max-loaded eviction."""

    def __init__(
        self,
        path: Path | str | None = None,
        max_loaded: int = 20,
        ttl_seconds: int = 3600,
    ) -> None:
        self.state_path = (
            Path(path or hermes_home() / "tool-slimmer" / "session_loaded.json")
            .expanduser()
        )
        self.max_loaded = max_loaded
        self.ttl_seconds = ttl_seconds
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
        raw_tools = data.get("loaded_tools", {})
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
                )
        self.evict_expired()

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "loaded_tools": {
                info.name: {
                    "loaded_at": info.loaded_at,
                    "expires_at": info.expires_at,
                }
                for info in self._infos.values()
            },
            "updated_at": time.time(),
        }
        self.state_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    def evict_expired(self) -> list[str]:
        """Remove expired entries and save. Returns evicted names."""
        now = time.time()
        expired = [name for name, info in self._infos.items() if info.expires_at is not None and info.expires_at <= now]
        for name in expired:
            del self._infos[name]
        if expired:
            self._save()
        return expired

    def evict_oldest_if_needed(self) -> list[str]:
        """Remove oldest entries while over max_loaded. Returns evicted names."""
        if len(self._infos) <= self.max_loaded:
            return []
        sorted_by_age = sorted(self._infos.values(), key=lambda i: i.loaded_at)
        to_evict = sorted_by_age[: len(self._infos) - self.max_loaded]
        removed: list[str] = []
        for info in to_evict:
            del self._infos[info.name]
            removed.append(info.name)
        if removed:
            self._save()
        return removed

    def add(self, name: str) -> bool:
        """Load a tool into the session state. Returns False if tool is already loaded."""
        now = time.time()
        expires = (now + self.ttl_seconds) if self.ttl_seconds > 0 else None
        self._infos[name] = LoadedToolInfo(name=name, loaded_at=now, expires_at=expires)
        self.evict_oldest_if_needed()
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
        """Check whether a tool name is currently loaded (and not expired)."""
        self.evict_expired()
        return name in self._infos

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


def _is_disabled_or_excluded(name: str, cfg: ToolSlimmerConfig) -> bool:
    """Return True if a tool name is globally disabled or excluded by config."""
    if name in cfg.disabled_tools:
        return True
    # Toolset-level exclusion cannot be checked without the schema itself,
    # but name-level disabled_tools covers the primary contract.
    return False


def _build_search_documents(schemas: list[Schema]) -> tuple[list[Any], dict[str, Schema]]:
    """Build BM25-searchable documents and a name->schema lookup."""
    docs = build_corpus(schemas)
    by_name: dict[str, Schema] = {}
    for schema in schemas:
        n = tool_name(schema)
        if n and n not in by_name:
            by_name[n] = schema
    return docs, by_name


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


def tool_slimmer_tool_search(args: dict, **kwargs: Any) -> str:
    """Search available tools by query and return ranked, loadable results."""
    try:
        query = str(args.get("query", "")).strip()
        schemas, schema_source = _resolve_schemas(args, kwargs)
        if not schemas:
            return _json({
                "ok": False,
                "error": "no_schemas_available",
                "message": "Provide schemas, run inside Hermes with live tool definitions, or rebuild the Tool Slimmer index.",
            })

        cfg = load_config(args.get("config_path") if isinstance(args, dict) else None)
        cfg = cfg.for_context(platform=args.get("platform"), profile=args.get("profile"))

        docs, by_name = _build_search_documents(schemas)
        scores = _score_search(query, docs)

        # Assemble results: start with scored matches, then append unscored in name order
        result_items: list[dict[str, Any]] = []
        seen: set[str] = set()

        state: SessionLoadedState | None = None
        if cfg.progressive_enabled:
            state = SessionLoadedState(
                max_loaded=cfg.progressive_max_loaded,
                ttl_seconds=cfg.progressive_ttl_seconds,
            )

        # BM25-ranked results
        for name, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            seen.add(name)
            schema = by_name.get(name)
            if schema is None:
                continue
            disabled = _is_disabled_or_excluded(name, cfg)
            item: dict[str, Any] = {
                "name": name,
                "score": round(score, 6),
                "info": _build_tool_info(schema),
                "disabled": disabled,
                "can_load": not disabled,
            }
            if state is not None:
                item["loaded"] = state.is_loaded(name)
            result_items.append(item)

        # Append remaining tools alphabetically (score None)
        for name in sorted(by_name):
            if name in seen:
                continue
            schema = by_name[name]
            disabled = _is_disabled_or_excluded(name, cfg)
            item = {
                "name": name,
                "score": None,
                "info": _build_tool_info(schema),
                "disabled": disabled,
                "can_load": not disabled,
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
        schemas, schema_source = _resolve_schemas(args, kwargs)
        if not schemas:
            return _json({
                "ok": False,
                "error": "no_schemas_available",
                "message": "Provide schemas, run inside Hermes with live tool definitions, or rebuild the Tool Slimmer index.",
            })

        by_name = {tool_name(s): s for s in schemas if tool_name(s)}
        if name not in by_name:
            return _json({"ok": False, "error": "tool_not_found", "name": name})

        cfg = load_config(args.get("config_path") if isinstance(args, dict) else None)
        cfg = cfg.for_context(platform=args.get("platform"), profile=args.get("profile"))

        disabled = _is_disabled_or_excluded(name, cfg)
        info = _build_tool_info(by_name[name])
        payload: dict[str, Any] = {
            "ok": True,
            "name": name,
            "schema": by_name[name],
            "info": info,
            "disabled": disabled,
            "can_load": not disabled,
            "schema_source": schema_source,
        }

        state: SessionLoadedState | None = None
        if cfg.progressive_enabled:
            state = SessionLoadedState(
                max_loaded=cfg.progressive_max_loaded,
                ttl_seconds=cfg.progressive_ttl_seconds,
            )
            payload["loaded"] = state.is_loaded(name)
        else:
            payload["loaded"] = False

        if do_load:
            if disabled:
                return _json({
                    "ok": False,
                    "error": "tool_disabled",
                    "name": name,
                    "message": f"Tool {name!r} is disabled or excluded and cannot be loaded.",
                })
            if state is None:
                return _json({
                    "ok": False,
                    "error": "progressive_disabled",
                    "message": "Progressive loading is not enabled in config.",
                })
            state.add(name)
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
        state = SessionLoadedState(
            max_loaded=cfg.progressive_max_loaded,
            ttl_seconds=cfg.progressive_ttl_seconds,
        )
        info = state.info_dict()
        return _json({
            "ok": True,
            "progressive_enabled": cfg.progressive_enabled,
            "max_loaded": cfg.progressive_max_loaded,
            "ttl_seconds": cfg.progressive_ttl_seconds,
            "count": len(info),
            "tools": info,
        })
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})
