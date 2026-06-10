from __future__ import annotations

import json
from pathlib import Path
from stat import S_IMODE
from typing import Any, cast
from unittest.mock import MagicMock

from hermes_tool_slimmer import register
from hermes_tool_slimmer.schemas import (
    CLEAR_VISIBLE_SKILL_PINS_SCHEMA,
    REQUEST_FULL_SKILL_INDEX_SCHEMA,
    SKILL_DETAILS_SCHEMA,
    SKILL_SEARCH_SCHEMA,
    VISIBLE_SKILL_PINS_SCHEMA,
)
from hermes_tool_slimmer.skills_tools import (
    FULL_SKILL_INDEX_REQUEST_MARKER,
    VisibleSkillPinState,
    tool_slimmer_clear_visible_skill_pins,
    tool_slimmer_request_full_skill_index,
    tool_slimmer_skill_details,
    tool_slimmer_skill_search,
    tool_slimmer_visible_skill_pins,
)


def _write_skill(root: Path, name: str, description: str, *, body: str = "") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\ntags: [alpha, beta]\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


def _schema_properties(schema: dict[str, Any]) -> dict[str, Any]:
    parameters = cast(dict[str, Any], schema["parameters"])
    return cast(dict[str, Any], parameters["properties"])


class TestSkillToolSchemas:
    def test_model_facing_schemas_do_not_accept_fabricated_skill_bodies(self) -> None:
        for schema in (SKILL_SEARCH_SCHEMA, SKILL_DETAILS_SCHEMA):
            properties = _schema_properties(schema)
            assert "body" not in properties
            assert "content" not in properties
            assert "skills" not in properties
            assert "schemas" not in properties
            assert "roots" not in properties
            parameters = cast(dict[str, Any], schema["parameters"])
            assert parameters["additionalProperties"] is False

    def test_request_and_pin_schemas_are_bounded(self) -> None:
        assert set(_schema_properties(REQUEST_FULL_SKILL_INDEX_SCHEMA)) == {"reason"}
        assert _schema_properties(VISIBLE_SKILL_PINS_SCHEMA) == {}
        assert _schema_properties(CLEAR_VISIBLE_SKILL_PINS_SCHEMA) == {}
        assert cast(dict[str, Any], REQUEST_FULL_SKILL_INDEX_SCHEMA["parameters"])["additionalProperties"] is False
        assert cast(dict[str, Any], VISIBLE_SKILL_PINS_SCHEMA["parameters"])["additionalProperties"] is False
        assert cast(dict[str, Any], CLEAR_VISIBLE_SKILL_PINS_SCHEMA["parameters"])["additionalProperties"] is False


class TestSkillSearchTool:
    def test_search_returns_ranked_metadata_only_results(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
        root = tmp_path / "skills"
        _write_skill(root, "hermes-profile-hygiene", "Profile resolver visibility diagnostics", body="BODY_SENTINEL_DO_NOT_LEAK")
        _write_skill(root, "creative-sketch", "Sketch a visual design")

        result = json.loads(tool_slimmer_skill_search({"query": "profile resolver", "limit": 5}, roots=[root]))

        assert result["ok"] is True
        assert result["metadata_only"] is True
        assert result["results"][0]["name"] == "hermes-profile-hygiene"
        assert result["results"][0]["full_instructions"].startswith("Use skill_view")
        serialized = json.dumps(result)
        assert "BODY_SENTINEL_DO_NOT_LEAK" not in serialized
        assert str(root) not in serialized

    def test_empty_query_returns_bounded_catalog_prefix(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
        root = tmp_path / "skills"
        _write_skill(root, "alpha", "Alpha skill")
        _write_skill(root, "beta", "Beta skill")

        result = json.loads(tool_slimmer_skill_search({"query": "", "limit": 1}, roots=[root]))

        assert result["ok"] is True
        assert result["count"] == 1


    def test_model_args_cannot_redirect_catalog_roots(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
        root = tmp_path / "skills"
        _write_skill(root, "hidden-from-default", "Should not be reached from model args")

        result = json.loads(
            tool_slimmer_skill_search(
                {"query": "hidden", "roots": [str(root)], "include_raw_paths": True}
            )
        )

        assert result["ok"] is True
        assert result["results"] == []
        assert str(root) not in json.dumps(result)


class TestSkillDetailsAndPins:
    def test_details_returns_metadata_and_can_pin_and_unpin(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
        root = tmp_path / "skills"
        _write_skill(root, "hermes-agent", "Configure Hermes Agent", body="BODY_SENTINEL_DO_NOT_LEAK")

        pinned = json.loads(
            tool_slimmer_skill_details(
                {"name": "hermes-agent", "pin_visible": True, "session_id": "s1"},
                roots=[root],
            )
        )
        assert pinned["ok"] is True
        assert pinned["pinned_visible"] is True
        assert pinned["pin_action"] == "pinned"
        assert "skill_view" in pinned["message"]
        assert "BODY_SENTINEL_DO_NOT_LEAK" not in json.dumps(pinned)

        pins = json.loads(tool_slimmer_visible_skill_pins({"session_id": "s1"}))
        assert pins["ok"] is True
        assert pins["count"] == 1
        assert "hermes-agent" in pins["visible_skill_pins"]

        unpinned = json.loads(
            tool_slimmer_skill_details(
                {"name": "hermes-agent", "unpin_visible": True, "session_id": "s1"},
                roots=[root],
            )
        )
        assert unpinned["ok"] is True
        assert unpinned["pin_action"] == "unpinned"
        assert unpinned["pinned_visible"] is False

    def test_visible_skill_pin_state_persists_and_uses_private_file(self, tmp_path: Path) -> None:
        state_path = tmp_path / "pins.json"
        root = tmp_path / "skills"
        _write_skill(root, "alpha", "Alpha skill")
        search = json.loads(tool_slimmer_skill_search({"query": "alpha"}, roots=[root]))
        assert search["ok"] is True

        from hermes_gizmo.skills_catalog import build_skill_catalog

        entry = build_skill_catalog(roots=[root]).entries[0]
        state = VisibleSkillPinState(path=state_path, session_id="s1")
        state.pin(entry)
        assert S_IMODE(state_path.stat().st_mode) == 0o600
        reopened = VisibleSkillPinState(path=state_path, session_id="s1")
        assert reopened.is_pinned("alpha") is True

    def test_clear_visible_skill_pins(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
        root = tmp_path / "skills"
        _write_skill(root, "alpha", "Alpha skill")
        tool_slimmer_skill_details({"name": "alpha", "pin_visible": True, "session_id": "s1"}, roots=[root])

        cleared = json.loads(tool_slimmer_clear_visible_skill_pins({"session_id": "s1"}))
        pins = json.loads(tool_slimmer_visible_skill_pins({"session_id": "s1"}))

        assert cleared["ok"] is True
        assert cleared["cleared"] == 1
        assert pins["count"] == 0

    def test_ttl_eviction(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        _write_skill(root, "alpha", "Alpha skill")
        from hermes_gizmo.skills_catalog import build_skill_catalog

        entry = build_skill_catalog(roots=[root]).entries[0]
        state = VisibleSkillPinState(path=tmp_path / "pins.json", ttl_seconds=1, session_id="s1")
        state.pin(entry)
        assert state.is_pinned("alpha") is True
        state._infos["alpha"].expires_at = 0
        assert state.is_pinned("alpha") is False


class TestRequestFullSkillIndex:
    def test_request_full_skill_index_returns_marker(self) -> None:
        result = json.loads(tool_slimmer_request_full_skill_index({"reason": "missing expected skill"}))

        assert result["ok"] is True
        assert result[FULL_SKILL_INDEX_REQUEST_MARKER] is True
        assert "diagnostic marker" in result["message"]
        assert result["reason"] == "missing expected skill"


class TestSkillToolRegistration:
    def test_register_exposes_skill_tools_under_legacy_and_gizmo_names(self) -> None:
        ctx = MagicMock()
        register(ctx)
        names = [call.kwargs["name"] for call in ctx.register_tool.call_args_list]

        for name in (
            "tool_slimmer_skill_search",
            "gizmo_skill_search",
            "tool_slimmer_skill_details",
            "gizmo_skill_details",
            "tool_slimmer_visible_skill_pins",
            "gizmo_visible_skill_pins",
            "tool_slimmer_clear_visible_skill_pins",
            "gizmo_clear_visible_skill_pins",
            "tool_slimmer_request_full_skill_index",
            "gizmo_request_full_skill_index",
        ):
            assert name in names

        assert "tool_slimmer_tool_search" in names
        assert "gizmo_tool_search" in names
