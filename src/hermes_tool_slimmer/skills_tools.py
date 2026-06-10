from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from hermes_gizmo.skills_catalog import (
    SkillCatalog,
    SkillCatalogEntry,
    SkillRoot,
    build_skill_catalog,
    diagnose_skill_catalog,
    search_skill_catalog,
)

from .config import hermes_home
from .private_io import write_private_json

FULL_SKILL_INDEX_REQUEST_MARKER = "gizmo_full_skill_index_requested"
_DEFAULT_MAX_PINS = 20
_DEFAULT_TTL_SECONDS = 3600


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


@dataclass
class VisibleSkillPinInfo:
    """Metadata for a single skill metadata entry pinned visible for a session."""

    name: str
    pinned_at: float
    expires_at: float | None
    last_seen_at: float = 0.0
    use_count: int = 0
    qualified_name: str | None = None
    category: str | None = None
    source_kind: str | None = None


class VisibleSkillPinState:
    """File-backed visible skill pin registry with per-session isolation, TTL, and LRU eviction.

    Skill pins only keep bounded catalog metadata visible in future reduced indexes.
    They do not load full ``SKILL.md`` instructions; agents must still call
    ``skill_view(name)`` before following a skill workflow.
    """

    def __init__(
        self,
        path: Path | str | None = None,
        max_pins: int = _DEFAULT_MAX_PINS,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        session_id: str | None = None,
    ) -> None:
        self.state_path = Path(path or hermes_home() / "gizmo" / "visible_skill_pins.json").expanduser()
        self.max_pins = max_pins
        self.ttl_seconds = ttl_seconds
        self.session_id = session_id or "__anonymous__"
        self._infos: dict[str, VisibleSkillPinInfo] = {}
        self._load()

    def _load(self) -> None:
        data: dict[str, Any] | None = None
        if self.state_path.exists():
            try:
                loaded = json.loads(self.state_path.read_text())
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, json.JSONDecodeError):
                data = None
        if not isinstance(data, dict):
            data = {}

        raw_pins: dict[str, Any] = {}
        if data.get("version") == 1:
            sessions = data.get("sessions", {})
            if isinstance(sessions, dict):
                session_data = sessions.get(self.session_id, {})
                if isinstance(session_data, dict):
                    raw = session_data.get("visible_skill_pins", {})
                    if isinstance(raw, dict):
                        raw_pins = raw

        self._infos = {}
        for name, entry in raw_pins.items():
            if not isinstance(entry, dict):
                continue
            pinned_at = float(entry.get("pinned_at", 0.0))
            expires_raw = entry.get("expires_at")
            expires_at = float(expires_raw) if expires_raw is not None else None
            self._infos[str(name)] = VisibleSkillPinInfo(
                name=str(name),
                pinned_at=pinned_at,
                expires_at=expires_at,
                last_seen_at=float(entry.get("last_seen_at", pinned_at)),
                use_count=int(entry.get("use_count", 0)),
                qualified_name=str(entry["qualified_name"]) if entry.get("qualified_name") is not None else None,
                category=str(entry["category"]) if entry.get("category") is not None else None,
                source_kind=str(entry["source_kind"]) if entry.get("source_kind") is not None else None,
            )
        self.evict_expired()

    def _save(self) -> None:
        sessions: dict[str, Any] = {}
        if self.state_path.exists():
            try:
                existing = json.loads(self.state_path.read_text())
                if isinstance(existing, dict) and existing.get("version") == 1:
                    raw_sessions = existing.get("sessions", {})
                    if isinstance(raw_sessions, dict):
                        sessions = raw_sessions
            except (OSError, json.JSONDecodeError):
                sessions = {}

        pins = {
            info.name: {
                "pinned_at": info.pinned_at,
                "expires_at": info.expires_at,
                "last_seen_at": info.last_seen_at,
                "use_count": info.use_count,
                "qualified_name": info.qualified_name,
                "category": info.category,
                "source_kind": info.source_kind,
            }
            for info in self._infos.values()
        }
        sessions[self.session_id] = {"visible_skill_pins": pins}
        write_private_json(
            self.state_path,
            {"version": 1, "sessions": sessions, "updated_at": time.time()},
            indent=2,
            sort_keys=True,
        )

    def evict_expired(self) -> list[str]:
        now = time.time()
        expired = [name for name, info in self._infos.items() if info.expires_at is not None and info.expires_at <= now]
        for name in expired:
            del self._infos[name]
        if expired:
            self._save()
        return expired

    def evict_lru_if_needed(self) -> list[str]:
        if len(self._infos) <= self.max_pins:
            return []
        by_lru = sorted(self._infos.values(), key=lambda info: (info.last_seen_at, info.pinned_at))
        removed: list[str] = []
        for info in by_lru[: len(self._infos) - self.max_pins]:
            del self._infos[info.name]
            removed.append(info.name)
        if removed:
            self._save()
        return removed

    def pin(self, entry: SkillCatalogEntry) -> bool:
        now = time.time()
        expires_at = (now + self.ttl_seconds) if self.ttl_seconds > 0 else None
        key = entry.qualified_name or entry.name
        existing = self._infos.get(key)
        self._infos[key] = VisibleSkillPinInfo(
            name=key,
            pinned_at=now,
            expires_at=expires_at,
            last_seen_at=now,
            use_count=(existing.use_count + 1) if existing else 1,
            qualified_name=entry.qualified_name,
            category=entry.category,
            source_kind=entry.source_kind,
        )
        self.evict_lru_if_needed()
        self._save()
        return True

    def unpin(self, name: str) -> bool:
        candidates = [name]
        for key, info in self._infos.items():
            if info.qualified_name == name and key not in candidates:
                candidates.append(key)
        removed = False
        for candidate in candidates:
            if candidate in self._infos:
                del self._infos[candidate]
                removed = True
        if removed:
            self._save()
        return removed

    def is_pinned(self, name: str) -> bool:
        self.evict_expired()
        info = self._infos.get(name)
        if info is None:
            for candidate in self._infos.values():
                if candidate.qualified_name == name:
                    info = candidate
                    break
        if info is None:
            return False
        info.last_seen_at = time.time()
        info.use_count += 1
        self._save()
        return True

    def info_dict(self) -> dict[str, dict[str, Any]]:
        self.evict_expired()
        now = time.time()
        return {
            name: {
                "pinned_at": info.pinned_at,
                "expires_at": info.expires_at,
                "last_seen_at": info.last_seen_at,
                "use_count": info.use_count,
                "qualified_name": info.qualified_name,
                "category": info.category,
                "source_kind": info.source_kind,
                "seconds_remaining": max(0.0, info.expires_at - now) if info.expires_at is not None else None,
            }
            for name, info in self._infos.items()
        }

    def clear(self) -> None:
        self._infos.clear()
        self._save()


def _get_session_id(args: dict[str, Any], kwargs: dict[str, Any]) -> str | None:
    if isinstance(args, dict):
        return args.get("session_id") or kwargs.get("session_id")
    return kwargs.get("session_id")


def _coerce_roots(raw_roots: Any) -> tuple[SkillRoot | Path | str, ...] | None:
    if raw_roots is None:
        return None
    if isinstance(raw_roots, (str, Path)):
        return (raw_roots,)
    if isinstance(raw_roots, Sequence):
        roots: list[SkillRoot | Path | str] = []
        for item in raw_roots:
            if isinstance(item, (str, Path, SkillRoot)):
                roots.append(item)
        return tuple(roots)
    return None


def _catalog_from_args(args: dict[str, Any], kwargs: dict[str, Any]) -> SkillCatalog:
    # roots/include_raw_paths/description_max_chars are intentionally kwargs-only.
    # Model-facing schemas do not expose them, and handler args should not be able
    # to redirect diagnostics to arbitrary local paths or raw-path rendering.
    roots = _coerce_roots(kwargs.get("roots"))
    description_max_chars = int(kwargs.get("description_max_chars") or 512)
    include_raw_paths = bool(kwargs.get("include_raw_paths", False))
    return build_skill_catalog(
        roots=roots,
        description_max_chars=description_max_chars,
        include_raw_paths=include_raw_paths,
    )


def _entry_to_dict(entry: SkillCatalogEntry, *, pinned: bool = False, score: float | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": entry.name,
        "qualified_name": entry.qualified_name,
        "category": entry.category,
        "description": entry.description,
        "description_truncated": entry.description_truncated,
        "source_kind": entry.source_kind,
        "source_label": entry.source_label,
        "tags": list(entry.tags),
        "related_skills": list(entry.related_skills),
        "conditions_summary": list(entry.conditions_summary),
        "has_references": entry.has_references,
        "has_templates": entry.has_templates,
        "has_scripts": entry.has_scripts,
        "trust_tier": entry.trust_tier,
        "pinned_visible": pinned,
        "full_instructions": "Use skill_view(name) to load full SKILL.md workflow instructions before following this skill.",
    }
    if score is not None:
        payload["score"] = score
    return payload


def _find_entry(catalog: SkillCatalog, name: str) -> SkillCatalogEntry | None:
    for entry in catalog.entries:
        if entry.name == name or entry.qualified_name == name:
            return entry
    return None


def tool_slimmer_skill_search(args: dict, **kwargs: Any) -> str:
    """Search resolver-visible skill metadata and return ranked metadata-only results."""
    try:
        query = str(args.get("query", "")).strip()
        limit = int(args.get("limit", 10))
        catalog = _catalog_from_args(args, kwargs)
        state = VisibleSkillPinState(session_id=_get_session_id(args, kwargs))
        if query:
            matches = search_skill_catalog(catalog, query, limit=limit)
        else:
            matches = list(catalog.entries[: max(0, limit)])
        results = [_entry_to_dict(entry, pinned=state.is_pinned(entry.qualified_name)) for entry in matches]
        diagnostics = diagnose_skill_catalog(catalog)
        return _json(
            {
                "ok": True,
                "query": query,
                "total_catalog_entries": len(catalog.entries),
                "results": results,
                "count": len(results),
                "diagnostics": {
                    "total_entries": diagnostics.total_entries,
                    "duplicate_names": list(diagnostics.duplicate_names),
                    "truncated_description_count": diagnostics.truncated_description_count,
                    "missing_always_include": list(diagnostics.missing_always_include),
                    "warnings": list(diagnostics.warnings),
                },
                "metadata_only": True,
            }
        )
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def tool_slimmer_skill_details(args: dict, **kwargs: Any) -> str:
    """Return metadata for one skill and optionally pin/unpin its visibility."""
    try:
        name = str(args.get("name", "")).strip()
        catalog = _catalog_from_args(args, kwargs)
        entry = _find_entry(catalog, name)
        if entry is None:
            return _json({"ok": False, "error": "skill_not_found", "name": name})
        state = VisibleSkillPinState(session_id=_get_session_id(args, kwargs))
        pin_visible = bool(args.get("pin_visible", False))
        unpin_visible = bool(args.get("unpin_visible", False))
        action = None
        if pin_visible:
            state.pin(entry)
            action = "pinned"
        elif unpin_visible:
            removed = state.unpin(entry.qualified_name)
            action = "unpinned" if removed else "not_pinned"
        pinned = state.is_pinned(entry.qualified_name)
        payload = _entry_to_dict(entry, pinned=pinned)
        payload.update(
            {
                "ok": True,
                "metadata_only": True,
                "pin_action": action,
                "message": "This returns skill metadata only. Call skill_view(name) to load full SKILL.md workflow instructions.",
            }
        )
        return _json(payload)
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def tool_slimmer_visible_skill_pins(args: dict, **kwargs: Any) -> str:
    """Return current visible skill pins for this session."""
    try:
        state = VisibleSkillPinState(session_id=_get_session_id(args, kwargs))
        pins = state.info_dict()
        return _json(
            {
                "ok": True,
                "session_id": _get_session_id(args, kwargs),
                "count": len(pins),
                "visible_skill_pins": pins,
                "metadata_only": True,
            }
        )
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def tool_slimmer_clear_visible_skill_pins(args: dict, **kwargs: Any) -> str:
    """Clear visible skill pins for this session."""
    try:
        state = VisibleSkillPinState(session_id=_get_session_id(args, kwargs))
        before = len(state.info_dict())
        state.clear()
        return _json({"ok": True, "cleared": before, "count": 0})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def tool_slimmer_request_full_skill_index(args: dict, **kwargs: Any) -> str:
    """Diagnostic marker requesting full skill-index visibility for a future core hook."""
    reason = args.get("reason") if isinstance(args, dict) else None
    payload: dict[str, Any] = {
        "ok": True,
        FULL_SKILL_INDEX_REQUEST_MARKER: True,
        "message": (
            "Full skill index visibility was requested. Phase 1.5 records a diagnostic marker only; "
            "a future Hermes core prompt hook must consume this marker before it can alter prompt rendering."
        ),
    }
    if reason:
        payload["reason"] = str(reason)
    return _json(payload)
