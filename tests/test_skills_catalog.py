"""Tests for read-only skill catalog diagnostics (Phase 1)."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from hermes_gizmo.skills_catalog import (
    SkillCatalog,
    SkillCatalogEntry,
    SkillRoot,
    _ResolverSkillMetadata,
    build_skill_catalog,
    default_skill_roots,
    diagnose_skill_catalog,
    format_skill_catalog_report,
    search_skill_catalog,
)

BODY_SENTINEL = "FULL-BODY-MUST-NOT-LEAK"


def write_skill(
    root: Path,
    dir_name: str,
    frontmatter: str,
    *,
    body: str = "",
    support_dirs: tuple[str, ...] = (),
) -> Path:
    skill_dir = root / dir_name
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    for sub in support_dirs:
        (skill_dir / sub).mkdir()
    return skill_dir


class TestFrontmatterParsing:
    def test_parses_metadata_fields(self, tmp_path: Path):
        write_skill(
            tmp_path,
            "profile-hygiene",
            "name: hermes-profile-hygiene\n"
            "category: hermes-platform\n"
            "description: Keep profile skill visibility healthy.\n"
            "tags: [profiles, governance]\n"
            "related_skills: [hermes-agent]\n"
            "platforms: [linux]\n"
            "required_tools: [skills_list]\n"
            "trust_tier: local-reviewed\n",
            support_dirs=("references", "scripts"),
        )

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local", "local")])

        assert not any("fallback frontmatter parse" in warning for warning in catalog.warnings)
        assert len(catalog.entries) == 1
        entry = catalog.entries[0]
        assert entry.name == "hermes-profile-hygiene"
        assert entry.qualified_name == "hermes-profile-hygiene"
        assert entry.category == "hermes-platform"
        assert entry.description == "Keep profile skill visibility healthy."
        assert entry.description_truncated is False
        assert entry.tags == ("profiles", "governance")
        assert entry.related_skills == ("hermes-agent",)
        assert entry.conditions_summary == ("platform:linux", "requires-tool:skills_list")
        assert entry.has_references is True
        assert entry.has_templates is False
        assert entry.has_scripts is True
        assert entry.trust_tier == "local-reviewed"

    def test_name_falls_back_to_directory(self, tmp_path: Path):
        write_skill(tmp_path, "dir-named-skill", "description: No explicit name.")

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])
        assert catalog.entries[0].name == "dir-named-skill"
        assert catalog.entries[0].category == "uncategorized"

    def test_category_falls_back_to_category_directory(self, tmp_path: Path):
        write_skill(
            tmp_path / "devops",
            "hermes-local-operations",
            "name: hermes-local-operations\ndescription: Operate local Hermes installs.",
        )

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])

        assert catalog.entries[0].name == "hermes-local-operations"
        assert catalog.entries[0].category == "devops"

    def test_frontmatter_category_overrides_category_directory(self, tmp_path: Path):
        write_skill(
            tmp_path / "devops",
            "hermes-local-operations",
            "name: hermes-local-operations\n"
            "category: hermes-platform\n"
            "description: Operate local Hermes installs.",
        )

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])

        assert catalog.entries[0].category == "hermes-platform"

    def test_fallback_iterator_warning_is_reported_when_resolver_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from hermes_gizmo import skills_catalog

        write_skill(tmp_path, "one", "name: one\ndescription: A skill.")
        monkeypatch.setattr(
            skills_catalog,
            "_resolve_skill_index_iterator",
            lambda: (
                skills_catalog._fallback_iter_skill_index_files,
                "Hermes resolver iterator unavailable; using best-effort local filesystem cataloging (test)",
            ),
        )

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])

        assert any("best-effort local filesystem cataloging" in warning for warning in catalog.warnings)
        assert catalog.entries[0].category == "uncategorized"

    def test_default_catalog_filters_to_resolver_visible_skills(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from hermes_gizmo import skills_catalog

        write_skill(tmp_path, "visible", "name: visible\ndescription: Unfiltered description.")
        write_skill(tmp_path, "disabled", "name: disabled\ndescription: Hidden by resolver.")
        monkeypatch.setattr(
            skills_catalog,
            "default_skill_roots",
            lambda: (SkillRoot(tmp_path, "local"),),
        )
        monkeypatch.setattr(
            skills_catalog,
            "_resolver_visible_skills",
            lambda: (
                {
                    "visible": _ResolverSkillMetadata(
                        name="visible",
                        description="Resolver description.",
                        category="resolver-category",
                    )
                },
                None,
            ),
        )

        catalog = build_skill_catalog()

        assert [entry.name for entry in catalog.entries] == ["visible"]
        assert catalog.entries[0].description == "Resolver description."
        assert catalog.entries[0].category == "resolver-category"

    def test_empty_resolver_visibility_returns_empty_default_catalog(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from hermes_gizmo import skills_catalog

        write_skill(tmp_path, "hidden", "name: hidden\ndescription: Hidden by resolver.")
        monkeypatch.setattr(
            skills_catalog,
            "default_skill_roots",
            lambda: (SkillRoot(tmp_path, "local"),),
        )
        monkeypatch.setattr(skills_catalog, "_resolver_visible_skills", lambda: ({}, None))

        catalog = build_skill_catalog()

        assert catalog.entries == ()

    def test_fallback_iterator_does_not_traverse_symlinked_directories(self, tmp_path: Path):
        allowed_root = tmp_path / "allowed"
        outside_root = tmp_path / "outside"
        write_skill(outside_root, "outside-skill", "name: outside-skill\ndescription: Outside.")
        allowed_root.mkdir()
        (allowed_root / "linked-outside").symlink_to(outside_root, target_is_directory=True)
        write_skill(allowed_root, "inside-skill", "name: inside-skill\ndescription: Inside.")

        catalog = build_skill_catalog([SkillRoot(allowed_root, "local")])

        assert [entry.name for entry in catalog.entries] == ["inside-skill"]

    def test_catalog_skips_symlinked_skill_file_outside_root(self, tmp_path: Path):
        allowed_root = tmp_path / "allowed"
        outside_root = tmp_path / "outside"
        outside_skill = write_skill(
            outside_root,
            "outside-skill",
            "name: outside-skill\ndescription: Outside.",
        )
        allowed_skill = allowed_root / "linked-skill"
        allowed_skill.mkdir(parents=True)
        (allowed_skill / "SKILL.md").symlink_to(outside_skill / "SKILL.md")
        write_skill(allowed_root, "inside-skill", "name: inside-skill\ndescription: Inside.")

        catalog = build_skill_catalog([SkillRoot(allowed_root, "local")])

        assert [entry.name for entry in catalog.entries] == ["inside-skill"]
        assert any("outside root boundary" in warning for warning in catalog.warnings)

    def test_fallback_iterator_enforces_boundary_with_resolver_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from hermes_gizmo import skills_catalog

        allowed_root = tmp_path / "allowed"
        outside_root = tmp_path / "outside"
        outside_skill = write_skill(
            outside_root,
            "outside-skill",
            "name: outside-skill\ndescription: Outside.",
        )
        allowed_skill = allowed_root / "linked-skill"
        allowed_skill.mkdir(parents=True)
        (allowed_skill / "SKILL.md").symlink_to(outside_skill / "SKILL.md")
        write_skill(allowed_root, "inside-skill", "name: inside-skill\ndescription: Inside.")
        monkeypatch.setattr(
            skills_catalog,
            "default_skill_roots",
            lambda: (SkillRoot(allowed_root, "local"),),
        )
        monkeypatch.setattr(
            skills_catalog,
            "_resolve_skill_index_iterator",
            lambda: (skills_catalog._fallback_iter_skill_index_files, None),
        )
        monkeypatch.setattr(
            skills_catalog,
            "_resolver_visible_skills",
            lambda: (
                {
                    "inside-skill": _ResolverSkillMetadata("inside-skill", "Inside.", None),
                    "outside-skill": _ResolverSkillMetadata("outside-skill", "Outside.", None),
                },
                None,
            ),
        )

        catalog = build_skill_catalog()

        assert [entry.name for entry in catalog.entries] == ["inside-skill"]
        assert any("outside root boundary" in warning for warning in catalog.warnings)

    def test_plugin_namespace_qualifies_name(self, tmp_path: Path):
        write_skill(tmp_path, "review", "name: review\ndescription: Plugin review skill.")

        catalog = build_skill_catalog(
            [SkillRoot(tmp_path, "plugin", "kanban", plugin_namespace="kanban")]
        )

        entry = catalog.entries[0]
        assert entry.qualified_name == "kanban:review"
        assert entry.source_kind == "plugin"
        assert entry.trust_tier == "unknown"

    def test_malformed_yaml_uses_fallback_with_warning(self, tmp_path: Path):
        write_skill(
            tmp_path,
            "broken",
            "name: broken-skill\ndescription: [unclosed",
        )

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])

        assert any("fallback" in warning for warning in catalog.warnings)
        assert catalog.entries[0].name == "broken-skill"

    def test_missing_frontmatter_yields_fallback_warning(self, tmp_path: Path):
        skill_dir = tmp_path / "no-frontmatter"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Just a body, no frontmatter.\n", encoding="utf-8")

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])

        assert any("fallback" in warning for warning in catalog.warnings)
        assert catalog.entries[0].name == "no-frontmatter"


class TestBoundedOutput:
    def test_description_truncated_and_flagged(self, tmp_path: Path):
        long_description = "word " * 300
        write_skill(tmp_path, "verbose", f"name: verbose\ndescription: {long_description}")

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")], description_max_chars=64)

        entry = catalog.entries[0]
        assert entry.description_truncated is True
        assert len(entry.description) <= 64

    def test_full_body_never_leaks_into_entries_or_report(self, tmp_path: Path):
        write_skill(
            tmp_path,
            "secretive",
            "name: secretive\ndescription: Short description.",
            body=f"# Instructions\n\n{BODY_SENTINEL}\n",
        )

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])
        report = format_skill_catalog_report(catalog)

        assert BODY_SENTINEL not in report
        for entry in catalog.entries:
            assert BODY_SENTINEL not in str(asdict(entry))


class TestSourceLabelRedaction:
    def test_path_like_labels_redacted_by_default(self, tmp_path: Path):
        write_skill(tmp_path, "private", "name: private\ndescription: Private skill.")

        catalog = build_skill_catalog(
            [SkillRoot(tmp_path, "external", str(tmp_path / "team-skills"))]
        )

        entry = catalog.entries[0]
        assert entry.source_label == "team-skills"
        assert "/" not in entry.source_label
        diagnostics = diagnose_skill_catalog(catalog)
        assert not any("raw path" in warning for warning in diagnostics.warnings)

    def test_windows_path_like_labels_redacted_by_default(self, tmp_path: Path):
        write_skill(tmp_path, "private", "name: private\ndescription: Private skill.")

        catalog = build_skill_catalog(
            [SkillRoot(tmp_path, "external", r"C:\Users\alice\team-skills")]
        )

        entry = catalog.entries[0]
        assert entry.source_label == "team-skills"
        assert "\\" not in entry.source_label
        diagnostics = diagnose_skill_catalog(catalog)
        assert not any("raw path" in warning for warning in diagnostics.warnings)

    def test_include_raw_paths_keeps_label_and_warns(self, tmp_path: Path):
        write_skill(tmp_path, "private", "name: private\ndescription: Private skill.")
        raw_label = str(tmp_path / "team-skills")

        catalog = build_skill_catalog(
            [SkillRoot(tmp_path, "external", raw_label)], include_raw_paths=True
        )

        assert catalog.entries[0].source_label == raw_label
        diagnostics = diagnose_skill_catalog(catalog)
        assert any("raw path" in warning for warning in diagnostics.warnings)

    def test_missing_root_warning_redacts_path(self, tmp_path: Path):
        catalog = build_skill_catalog([SkillRoot(tmp_path / "absent-root", "local")])

        assert catalog.entries == ()
        assert any("absent-root" in warning for warning in catalog.warnings)
        assert not any(str(tmp_path) in warning for warning in catalog.warnings)


class TestDiagnostics:
    def test_duplicate_detection_across_roots(self, tmp_path: Path):
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        write_skill(root_a, "shared", "name: shared-skill\ndescription: First copy.")
        write_skill(root_b, "shared", "name: shared-skill\ndescription: Second copy.")

        catalog = build_skill_catalog(
            [SkillRoot(root_a, "local"), SkillRoot(root_b, "external")]
        )
        diagnostics = diagnose_skill_catalog(catalog)

        assert diagnostics.total_entries == 2
        assert diagnostics.duplicate_names == ("shared-skill",)
        assert any("duplicate" in warning for warning in diagnostics.warnings)

    def test_missing_always_include_reported(self, tmp_path: Path):
        write_skill(tmp_path, "present", "name: present\ndescription: Present skill.")

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])
        diagnostics = diagnose_skill_catalog(
            catalog, always_include=["present", "hermes-agent", "systematic-debugging"]
        )

        assert diagnostics.missing_always_include == (
            "hermes-agent",
            "systematic-debugging",
        )
        assert any("always-include" in warning for warning in diagnostics.warnings)

    def test_truncation_count(self, tmp_path: Path):
        write_skill(tmp_path, "short", "name: short\ndescription: Fine.")
        write_skill(tmp_path, "long", f"name: long\ndescription: {'x' * 700}")

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])
        diagnostics = diagnose_skill_catalog(catalog)

        assert diagnostics.truncated_description_count == 1

    def test_report_includes_summary_lines(self, tmp_path: Path):
        write_skill(tmp_path, "present", "name: present\ndescription: Present skill.")

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])
        report = format_skill_catalog_report(catalog, always_include=["missing-one"])

        assert "total entries: 1" in report
        assert "missing always-include: missing-one" in report
        assert "present" in report


class TestSearch:
    def test_search_ranks_name_matches_first(self, tmp_path: Path):
        write_skill(
            tmp_path,
            "profile-hygiene",
            "name: hermes-profile-hygiene\ndescription: Profile visibility hygiene.",
        )
        write_skill(
            tmp_path,
            "debugging",
            "name: systematic-debugging\ndescription: Debug profile issues methodically.",
        )

        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])
        results = search_skill_catalog(catalog, "profile hygiene")

        assert [entry.name for entry in results][0] == "hermes-profile-hygiene"

    def test_search_empty_query_or_no_match(self, tmp_path: Path):
        write_skill(tmp_path, "one", "name: one\ndescription: A skill.")
        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])

        assert search_skill_catalog(catalog, "") == []
        assert search_skill_catalog(catalog, "zzzz-nothing-matches") == []

    def test_search_respects_limit_and_accepts_entry_sequences(self, tmp_path: Path):
        for index in range(5):
            write_skill(
                tmp_path,
                f"skill-{index}",
                f"name: review-skill-{index}\ndescription: Review helper {index}.",
            )
        catalog = build_skill_catalog([SkillRoot(tmp_path, "local")])

        results = search_skill_catalog(list(catalog.entries), "review", limit=2)

        assert len(results) == 2
        assert all(isinstance(entry, SkillCatalogEntry) for entry in results)


class TestDefaultRoots:
    def test_default_root_is_hermes_home_skills(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        write_skill(tmp_path / "skills", "homed", "name: homed\ndescription: Home skill.")

        roots = default_skill_roots()
        assert roots == (SkillRoot(tmp_path / "skills", "local", "local"),)

        catalog = build_skill_catalog()
        assert [entry.name for entry in catalog.entries] == ["homed"]
        assert catalog.entries[0].source_label == "local"


class TestCompatibilityShim:
    def test_legacy_module_reexports_canonical_symbols(self):
        from hermes_tool_slimmer import skills_catalog as legacy

        assert legacy.SkillCatalogEntry is SkillCatalogEntry
        assert legacy.SkillCatalog is SkillCatalog
        assert legacy.build_skill_catalog is build_skill_catalog
        assert legacy.search_skill_catalog is search_skill_catalog
        assert legacy.diagnose_skill_catalog is diagnose_skill_catalog
        assert legacy.format_skill_catalog_report is format_skill_catalog_report
