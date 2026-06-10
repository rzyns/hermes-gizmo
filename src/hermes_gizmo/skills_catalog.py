"""Read-only skill catalog diagnostics (Phase 1 of skill progressive disclosure).

This module builds a bounded, sanitized metadata catalog from explicit skill
roots (or the default ``HERMES_HOME/skills`` root), and reports invariant
diagnostics: duplicates, description truncation, missing always-include
entries, and redaction warnings.

It is deliberately diagnostic-only:

- it never mutates skills or configuration;
- it never includes full ``SKILL.md`` bodies in entries or reports;
- it never renders raw filesystem paths by default;
- it does not perform live prompt slimming or selection.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable, Sequence

import yaml

from hermes_tool_slimmer.config import hermes_home
from hermes_tool_slimmer.tokenizer import tokenize

DEFAULT_DESCRIPTION_MAX_CHARS = 512
_FRONTMATTER_MAX_CHARS = 32768
_MAX_LIST_ITEMS = 16
_MAX_LIST_ITEM_CHARS = 80
_MAX_CONDITIONS = 8

_SOURCE_KINDS = ("local", "external", "plugin", "bundled", "profile_local")
_WHITESPACE_RE = re.compile(r"\s+")
_NAIVE_KV_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
_EXCLUDED_SKILL_DIRS = frozenset(
    {
        ".git",
        ".github",
        ".hub",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
)


@dataclass(frozen=True)
class SkillRoot:
    """One directory of skills with provenance metadata.

    ``source_label`` is a human-readable provenance label; it is sanitized to
    a non-path label by default during catalog construction.
    """

    path: Path
    source_kind: str = "local"
    source_label: str | None = None
    plugin_namespace: str | None = None


@dataclass(frozen=True)
class SkillCatalogEntry:
    """Bounded, sanitized metadata for one resolver-visible skill."""

    name: str
    qualified_name: str
    category: str
    description: str
    description_truncated: bool
    source_kind: str
    source_label: str | None
    tags: tuple[str, ...] = ()
    related_skills: tuple[str, ...] = ()
    conditions_summary: tuple[str, ...] = ()
    has_references: bool = False
    has_templates: bool = False
    has_scripts: bool = False
    trust_tier: str | None = None


@dataclass(frozen=True)
class SkillCatalog:
    """Catalog entries plus best-effort warnings gathered during the build."""

    entries: tuple[SkillCatalogEntry, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillCatalogDiagnostics:
    """Invariant-check summary over a built skill catalog."""

    total_entries: int
    duplicate_names: tuple[str, ...]
    truncated_description_count: int
    missing_always_include: tuple[str, ...]
    warnings: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class _ResolverSkillMetadata:
    """Minimal metadata returned by Hermes' resolver-backed ``skills_list``."""

    name: str
    description: str
    category: str | None


def default_skill_roots() -> tuple[SkillRoot, ...]:
    """Default catalog roots: only ``HERMES_HOME/skills``, never arbitrary dirs."""

    return (SkillRoot(path=hermes_home() / "skills", source_kind="local", source_label="local"),)


def build_skill_catalog(
    roots: Sequence[SkillRoot | Path | str] | None = None,
    *,
    description_max_chars: int = DEFAULT_DESCRIPTION_MAX_CHARS,
    include_raw_paths: bool = False,
) -> SkillCatalog:
    """Build a read-only catalog from explicit skill roots.

    Each resolver-discovered ``SKILL.md`` under an allowed root becomes one
    candidate entry. When default roots are used and Hermes ``skills_list`` is
    importable, the final catalog is filtered to resolver-visible skill names.
    Parsing is best-effort: unreadable or malformed skills produce warnings
    instead of failures, and only frontmatter is ever retained.
    """

    use_resolver_visibility = roots is None
    skill_roots = [_coerce_root(root) for root in (roots if roots is not None else default_skill_roots())]
    entries: list[SkillCatalogEntry] = []
    warnings: list[str] = []
    iter_skill_index_files, resolver_warning = _resolve_skill_index_iterator()
    using_fallback_iterator = iter_skill_index_files is _fallback_iter_skill_index_files
    if resolver_warning:
        warnings.append(resolver_warning)
    resolver_metadata, resolver_metadata_warning = (
        _resolver_visible_skills() if use_resolver_visibility else (None, None)
    )
    if resolver_metadata_warning:
        warnings.append(resolver_metadata_warning)
    enforce_root_boundary = using_fallback_iterator or resolver_metadata is None

    for root in skill_roots:
        root_path = root.path.expanduser()
        if not root_path.is_dir():
            warnings.append(f"skill root not found: {_safe_label(str(root_path), include_raw_paths)}")
            continue
        for skill_md in iter_skill_index_files(root_path, "SKILL.md"):
            if any(part in _EXCLUDED_SKILL_DIRS for part in skill_md.parts):
                continue
            if enforce_root_boundary and not _path_within_root(skill_md, root_path):
                warnings.append(
                    "skipping skill outside root boundary: "
                    f"{_safe_label(str(skill_md), include_raw_paths)}"
                )
                continue
            skill_dir = skill_md.parent
            entry, entry_warnings = _build_entry(
                skill_dir,
                skill_md,
                root,
                root_path=root_path,
                description_max_chars=description_max_chars,
                include_raw_paths=include_raw_paths,
            )
            warnings.extend(entry_warnings)
            if entry is not None:
                entries.append(entry)

    if resolver_metadata is not None:
        entries = _filter_to_resolver_visible(entries, resolver_metadata, description_max_chars)

    entries.sort(key=lambda entry: (entry.qualified_name, entry.source_kind))
    return SkillCatalog(entries=tuple(entries), warnings=tuple(warnings))


def search_skill_catalog(
    catalog: SkillCatalog | Sequence[SkillCatalogEntry],
    query: str,
    *,
    limit: int = 10,
) -> list[SkillCatalogEntry]:
    """Rank catalog entries by token overlap with the query (read-only)."""

    entries = _catalog_entries(catalog)
    query_tokens = set(tokenize(query))
    if not query_tokens or limit <= 0:
        return []

    scored: list[tuple[float, SkillCatalogEntry]] = []
    for entry in entries:
        name_tokens = set(tokenize(entry.name)) | set(tokenize(entry.qualified_name))
        meta_tokens = set(tokenize(entry.category)) | set(tokenize(" ".join(entry.tags)))
        description_tokens = set(tokenize(entry.description))
        score = (
            3.0 * len(query_tokens & name_tokens)
            + 2.0 * len(query_tokens & meta_tokens)
            + 1.0 * len(query_tokens & description_tokens)
        )
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda item: (-item[0], item[1].qualified_name))
    return [entry for _, entry in scored[:limit]]


def diagnose_skill_catalog(
    catalog: SkillCatalog | Sequence[SkillCatalogEntry],
    *,
    always_include: Sequence[str] = (),
) -> SkillCatalogDiagnostics:
    """Run invariant checks over a built catalog."""

    entries = _catalog_entries(catalog)
    warnings = list(catalog.warnings) if isinstance(catalog, SkillCatalog) else []

    seen: dict[str, int] = {}
    for entry in entries:
        seen[entry.qualified_name] = seen.get(entry.qualified_name, 0) + 1
    duplicates = tuple(sorted(name for name, count in seen.items() if count > 1))
    for name in duplicates:
        warnings.append(f"duplicate skill entries for: {name}")

    truncated = sum(1 for entry in entries if entry.description_truncated)

    known = {entry.name for entry in entries} | {entry.qualified_name for entry in entries}
    missing = tuple(sorted(name for name in always_include if name not in known))
    for name in missing:
        warnings.append(f"always-include skill missing from catalog: {name}")

    for entry in entries:
        if entry.source_label and _looks_like_path(entry.source_label):
            warnings.append(
                f"source label for {entry.qualified_name} looks like a raw path; "
                "raw paths should not be prompt- or report-rendered by default"
            )

    return SkillCatalogDiagnostics(
        total_entries=len(entries),
        duplicate_names=duplicates,
        truncated_description_count=truncated,
        missing_always_include=missing,
        warnings=tuple(warnings),
    )


def format_skill_catalog_report(
    catalog: SkillCatalog | Sequence[SkillCatalogEntry],
    diagnostics: SkillCatalogDiagnostics | None = None,
    *,
    always_include: Sequence[str] = (),
) -> str:
    """Render a compact text report; metadata only, never skill bodies."""

    entries = _catalog_entries(catalog)
    if diagnostics is None:
        diagnostics = diagnose_skill_catalog(catalog, always_include=always_include)

    lines = [
        "Skill catalog diagnostics (read-only)",
        f"  total entries: {diagnostics.total_entries}",
        f"  duplicate names: {', '.join(diagnostics.duplicate_names) or 'none'}",
        f"  truncated descriptions: {diagnostics.truncated_description_count}",
        f"  missing always-include: {', '.join(diagnostics.missing_always_include) or 'none'}",
    ]
    if diagnostics.warnings:
        lines.append("  warnings:")
        lines.extend(f"    - {warning}" for warning in diagnostics.warnings)
    if entries:
        lines.append("  entries:")
        for entry in entries:
            flags = "".join(
                marker
                for marker, present in (
                    ("R", entry.has_references),
                    ("T", entry.has_templates),
                    ("S", entry.has_scripts),
                )
                if present
            )
            suffix = f" [{flags}]" if flags else ""
            truncated = " (truncated)" if entry.description_truncated else ""
            lines.append(
                f"    - {entry.qualified_name} ({entry.category}, {entry.source_kind})"
                f"{suffix}: {entry.description}{truncated}"
            )
    return "\n".join(lines)


def _coerce_root(root: SkillRoot | Path | str) -> SkillRoot:
    if isinstance(root, SkillRoot):
        return root
    return SkillRoot(path=Path(root), source_kind="local")


def _catalog_entries(
    catalog: SkillCatalog | Sequence[SkillCatalogEntry],
) -> tuple[SkillCatalogEntry, ...]:
    if isinstance(catalog, SkillCatalog):
        return catalog.entries
    return tuple(catalog)


def _build_entry(
    skill_dir: Path,
    skill_md: Path,
    root: SkillRoot,
    *,
    root_path: Path,
    description_max_chars: int,
    include_raw_paths: bool,
) -> tuple[SkillCatalogEntry | None, list[str]]:
    warnings: list[str] = []
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")[:_FRONTMATTER_MAX_CHARS]
    except OSError as exc:
        warnings.append(f"could not read skill {skill_dir.name}: {exc.__class__.__name__}")
        return None, warnings

    frontmatter, used_fallback = _parse_frontmatter(text)
    if used_fallback:
        warnings.append(
            f"best-effort fallback frontmatter parse for skill {skill_dir.name}"
        )

    name = _clean_line(frontmatter.get("name"), _MAX_LIST_ITEM_CHARS) or skill_dir.name
    if root.plugin_namespace:
        qualified_name = f"{root.plugin_namespace}:{name}"
    else:
        qualified_name = _clean_line(frontmatter.get("qualified_name"), _MAX_LIST_ITEM_CHARS) or name

    description, truncated = _clean_text(
        frontmatter.get("description"), description_max_chars
    )

    source_kind = root.source_kind if root.source_kind in _SOURCE_KINDS else "external"
    source_label = _safe_label(root.source_label or source_kind, include_raw_paths)

    trust_tier = _clean_line(frontmatter.get("trust_tier") or frontmatter.get("trust"), 32) or None
    if trust_tier is None and source_kind in ("external", "plugin", "profile_local"):
        trust_tier = "unknown"

    entry = SkillCatalogEntry(
        name=name,
        qualified_name=qualified_name,
        category=(
            _clean_line(frontmatter.get("category"), _MAX_LIST_ITEM_CHARS)
            or _category_from_path(skill_md, root_path)
            or "uncategorized"
        ),
        description=description,
        description_truncated=truncated,
        source_kind=source_kind,
        source_label=source_label,
        tags=_clean_tuple(frontmatter.get("tags")),
        related_skills=_clean_tuple(
            frontmatter.get("related_skills") or frontmatter.get("related")
        ),
        conditions_summary=_conditions_summary(frontmatter),
        has_references=(skill_dir / "references").is_dir(),
        has_templates=(skill_dir / "templates").is_dir(),
        has_scripts=(skill_dir / "scripts").is_dir(),
        trust_tier=trust_tier,
    )
    return entry, warnings


SkillIndexIterator = Callable[[Path, str], Iterable[Path]]


def _resolve_skill_index_iterator() -> tuple[SkillIndexIterator, str | None]:
    """Use Hermes' resolver iterator when available, else a bounded fallback."""

    try:
        from agent.skill_utils import iter_skill_index_files  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - exact import state is environment-specific
        return (
            _fallback_iter_skill_index_files,
            "Hermes resolver iterator unavailable; using best-effort local filesystem cataloging "
            f"({exc.__class__.__name__})",
        )
    return iter_skill_index_files, None


def _resolver_visible_skills() -> tuple[dict[str, _ResolverSkillMetadata] | None, str | None]:
    """Return Hermes ``skills_list`` metadata when importable in this runtime."""

    try:
        from tools.skills_tool import skills_list  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - exact import state is environment-specific
        return (
            None,
            "Hermes skills_list resolver metadata unavailable; catalog may include "
            f"non-visible skills ({exc.__class__.__name__})",
        )

    try:
        payload = json.loads(skills_list())
    except Exception as exc:  # pragma: no cover - defensive against host resolver errors
        return (
            None,
            "Hermes skills_list resolver metadata failed; catalog may include "
            f"non-visible skills ({exc.__class__.__name__})",
        )

    if not isinstance(payload, dict) or payload.get("success") is not True:
        return (None, "Hermes skills_list resolver metadata returned an unsuccessful payload")

    raw_skills = payload.get("skills")
    if not isinstance(raw_skills, list):
        return (None, "Hermes skills_list resolver metadata omitted the skills list")

    metadata: dict[str, _ResolverSkillMetadata] = {}
    for raw_skill in raw_skills:
        if not isinstance(raw_skill, dict):
            continue
        raw_name = raw_skill.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        raw_description = raw_skill.get("description")
        raw_category = raw_skill.get("category")
        name = raw_name.strip()
        metadata[name] = _ResolverSkillMetadata(
            name=name,
            description=raw_description.strip() if isinstance(raw_description, str) else "",
            category=raw_category.strip() if isinstance(raw_category, str) and raw_category.strip() else None,
        )
    return metadata, None


def _filter_to_resolver_visible(
    entries: Sequence[SkillCatalogEntry],
    resolver_metadata: dict[str, _ResolverSkillMetadata],
    description_max_chars: int,
) -> list[SkillCatalogEntry]:
    """Keep only Hermes resolver-visible skills and mirror resolver metadata."""

    filtered: list[SkillCatalogEntry] = []
    seen: set[str] = set()
    for entry in entries:
        metadata = resolver_metadata.get(entry.name)
        if metadata is None or metadata.name in seen:
            continue
        description, description_truncated = _clean_text(
            metadata.description or entry.description,
            description_max_chars,
        )
        filtered.append(
            replace(
                entry,
                description=description,
                description_truncated=description_truncated,
                category=metadata.category or entry.category,
            )
        )
        seen.add(metadata.name)
    return filtered


def _fallback_iter_skill_index_files(skills_dir: Path, filename: str) -> Iterable[Path]:
    """Fallback matching Hermes' sorted, exclusion-pruned SKILL.md iteration."""

    matches: list[Path] = []
    for root, dirs, files in os.walk(skills_dir, followlinks=False):
        dirs[:] = [directory for directory in dirs if directory not in _EXCLUDED_SKILL_DIRS]
        if filename in files:
            matches.append(Path(root) / filename)
    yield from sorted(matches, key=lambda path: str(path.relative_to(skills_dir)))


def _category_from_path(skill_md: Path, root_path: Path) -> str | None:
    """Mirror Hermes category-folder semantics for ``category/skill/SKILL.md``."""

    try:
        relative = skill_md.relative_to(root_path)
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) >= 3:
        return _clean_line(parts[0], _MAX_LIST_ITEM_CHARS)
    return None


def _path_within_root(path: Path, root_path: Path) -> bool:
    """Reject symlinked skill paths whose real target escapes the root."""

    try:
        path.resolve().relative_to(root_path.resolve())
    except (OSError, ValueError):
        return False
    return True


def _parse_frontmatter(text: str) -> tuple[dict[str, object], bool]:
    """Extract the leading ``---`` frontmatter block; never retain the body."""

    lines = text.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or lines[index].strip() != "---":
        return {}, True

    block: list[str] = []
    for line in lines[index + 1 :]:
        if line.strip() == "---":
            break
        block.append(line)
    else:
        return {}, True

    raw = "\n".join(block)
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        return _naive_frontmatter(block), True
    if isinstance(parsed, dict):
        return {str(key): value for key, value in parsed.items()}, False
    return _naive_frontmatter(block), True


def _naive_frontmatter(block: list[str]) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for line in block:
        match = _NAIVE_KV_RE.match(line)
        if match:
            parsed[match.group(1)] = match.group(2).strip()
    return parsed


def _clean_text(value: object, max_chars: int) -> tuple[str, bool]:
    text = _WHITESPACE_RE.sub(" ", str(value or "")).strip()
    if len(text) > max_chars:
        return text[: max(0, max_chars - 1)].rstrip() + "…", True
    return text, False


def _clean_line(value: object, max_chars: int) -> str:
    cleaned, _ = _clean_text(value, max_chars)
    return cleaned


def _clean_tuple(value: object, max_items: int = _MAX_LIST_ITEMS) -> tuple[str, ...]:
    if isinstance(value, str):
        items: list[object] = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return ()
    cleaned = [_clean_line(item, _MAX_LIST_ITEM_CHARS) for item in items[:max_items]]
    return tuple(item for item in cleaned if item)


def _conditions_summary(frontmatter: dict[str, object]) -> tuple[str, ...]:
    summary: list[str] = []
    for platform in _clean_tuple(frontmatter.get("platforms")):
        summary.append(f"platform:{platform}")
    for tool in _clean_tuple(frontmatter.get("required_tools") or frontmatter.get("requires_tools")):
        summary.append(f"requires-tool:{tool}")
    for toolset in _clean_tuple(frontmatter.get("required_toolsets")):
        summary.append(f"requires-toolset:{toolset}")
    condition = _clean_line(frontmatter.get("when") or frontmatter.get("condition"), _MAX_LIST_ITEM_CHARS)
    if condition:
        summary.append(f"when:{condition}")
    return tuple(summary[:_MAX_CONDITIONS])


def _looks_like_path(label: str) -> bool:
    return "/" in label or "\\" in label or label.startswith("~")


def _safe_label(label: str, include_raw_paths: bool) -> str:
    if include_raw_paths or not _looks_like_path(label):
        return label
    stripped = label.rstrip("/\\")
    parts = [part for part in re.split(r"[/\\]+", stripped) if part]
    return parts[-1] if parts else "redacted"
