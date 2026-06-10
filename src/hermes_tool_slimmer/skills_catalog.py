"""Compatibility alias for :mod:`hermes_gizmo.skills_catalog`.

The skill catalog diagnostics module is canonical under the
:mod:`hermes_gizmo` namespace; this shim re-exports it for the legacy
``hermes_tool_slimmer`` import surface.
"""

from __future__ import annotations

from hermes_gizmo.skills_catalog import (
    DEFAULT_DESCRIPTION_MAX_CHARS,
    SkillCatalog,
    SkillCatalogDiagnostics,
    SkillCatalogEntry,
    SkillRoot,
    build_skill_catalog,
    default_skill_roots,
    diagnose_skill_catalog,
    format_skill_catalog_report,
    search_skill_catalog,
)

__all__ = [
    "DEFAULT_DESCRIPTION_MAX_CHARS",
    "SkillCatalog",
    "SkillCatalogDiagnostics",
    "SkillCatalogEntry",
    "SkillRoot",
    "build_skill_catalog",
    "default_skill_roots",
    "diagnose_skill_catalog",
    "format_skill_catalog_report",
    "search_skill_catalog",
]
