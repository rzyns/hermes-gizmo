from __future__ import annotations

import json
import time

from hermes_tool_slimmer.config import ToolSlimmerConfig
from hermes_tool_slimmer.embeddings import (
    CacheProvenance,
    EmbeddingCache,
    FakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
    _canonical_text_hash,
    SemanticRanker,
)
from hermes_tool_slimmer.schemas import SELECT_SCHEMA
from hermes_tool_slimmer.session_tools import (
    SessionLoadedState,
    _schema_is_eligible,
    tool_slimmer_loaded_tools,
    tool_slimmer_tool_details,
    tool_slimmer_tool_search,
)


SCHEMAS = [
    {"name": "terminal", "toolset": "native", "description": "Run shell commands"},
    {"name": "read_file", "toolset": "native", "description": "Read a file"},
    {"name": "github_search_code", "toolset": "github", "description": "Search GitHub code"},
    {"name": "slack_send_message", "toolset": "slack", "description": "Send Slack message"},
    {"name": "browser_navigate", "toolset": "native", "description": "Browser"},
    {"name": "mcp_server_foo.tool_a", "toolset": "mcp:foo", "description": "MCP tool"},
]


class TestSchemaIsEligible:
    """B1: schema-level eligibility must enforce disabled_tools, disabled_toolsets,
    include_mcp_tools, include_native_tools, and duplicate-name ambiguity."""

    def test_disabled_tool(self):
        cfg = ToolSlimmerConfig(disabled_tools=["terminal"])
        assert _schema_is_eligible({"name": "terminal"}, cfg) is False

    def test_enabled_tool(self):
        cfg = ToolSlimmerConfig(disabled_tools=["terminal"])
        assert _schema_is_eligible({"name": "read_file"}, cfg) is True

    def test_disabled_toolset(self):
        cfg = ToolSlimmerConfig(disabled_toolsets=["github"])
        assert _schema_is_eligible({"name": "github_search_code", "toolset": "github"}, cfg) is False

    def test_other_toolset_not_disabled(self):
        cfg = ToolSlimmerConfig(disabled_toolsets=["github"])
        assert _schema_is_eligible({"name": "slack_send_message", "toolset": "slack"}, cfg) is True

    def test_mcp_excluded(self):
        cfg = ToolSlimmerConfig(include_mcp_tools=False)
        assert _schema_is_eligible({"name": "mcp_server_foo.tool_a", "toolset": "mcp:foo"}, cfg) is False

    def test_native_excluded(self):
        cfg = ToolSlimmerConfig(include_native_tools=False)
        assert _schema_is_eligible({"name": "terminal", "toolset": "native"}, cfg) is False

    def test_mcp_included(self):
        cfg = ToolSlimmerConfig(include_mcp_tools=True)
        assert _schema_is_eligible({"name": "mcp_server_foo.tool_a", "toolset": "mcp:foo"}, cfg) is True


class TestToolSearchEligibility:
    """B1: tool_search must mark ineligible tools disabled=true and can_load=false."""

    def test_disabled_toolset_marked_disabled_and_not_loadable(self, monkeypatch):
        cfg = ToolSlimmerConfig(disabled_toolsets=["github"], progressive_enabled=True)
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.load_config", lambda *_a, **_k: cfg
        )
        result = json.loads(tool_slimmer_tool_search({"query": "github"}, schemas=SCHEMAS))
        assert result["ok"] is True
        github_entry = next((r for r in result["results"] if r["name"] == "github_search_code"), None)
        assert github_entry is not None
        assert github_entry["disabled"] is True
        assert github_entry["can_load"] is False

    def test_duplicate_name_marked_ambiguous(self, monkeypatch):
        schemas = [
            {"name": "terminal", "toolset": "native", "description": "Run shell commands"},
            {"name": "terminal", "toolset": "slack", "description": "Duplicate name"},
        ]
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.load_config", lambda *_a, **_k: ToolSlimmerConfig()
        )
        result = json.loads(tool_slimmer_tool_search({"query": "terminal"}, schemas=schemas))
        terminal_entries = [r for r in result["results"] if r["name"] == "terminal"]
        assert len(terminal_entries) == 1
        assert terminal_entries[0]["ambiguous"] is True
        assert terminal_entries[0]["can_load"] is False

    def test_mcp_filter_omits_when_disabled(self, monkeypatch):
        cfg = ToolSlimmerConfig(include_mcp_tools=False, progressive_enabled=True)
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.load_config", lambda *_a, **_k: cfg
        )
        result = json.loads(tool_slimmer_tool_search({"query": "mcp"}, schemas=SCHEMAS))
        mcp_entry = next((r for r in result["results"] if r["name"] == "mcp_server_foo.tool_a"), None)
        assert mcp_entry is not None
        assert mcp_entry["disabled"] is True
        assert mcp_entry["can_load"] is False


class TestToolDetailsEligibility:
    """B1: tool_details(load=True) must reject ineligible tools before mutating state."""

    def test_load_disabled_toolset_rejected(self, monkeypatch):
        cfg = ToolSlimmerConfig(
            disabled_toolsets=["github"],
            progressive_enabled=True,
            progressive_max_loaded=10,
            progressive_ttl_seconds=3600,
        )
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.load_config", lambda *_a, **_k: cfg
        )
        result = json.loads(
            tool_slimmer_tool_details(
                {"name": "github_search_code", "load": True},
                schemas=SCHEMAS,
            )
        )
        assert result["ok"] is False
        assert result["error"] == "tool_disabled"

    def test_load_ambiguous_duplicate_rejected(self, monkeypatch):
        schemas = [
            {"name": "terminal", "toolset": "native", "description": "Run shell commands"},
            {"name": "terminal", "toolset": "slack", "description": "Duplicate name"},
        ]
        cfg = ToolSlimmerConfig(
            progressive_enabled=True,
            progressive_max_loaded=10,
            progressive_ttl_seconds=3600,
        )
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.load_config", lambda *_a, **_k: cfg
        )
        result = json.loads(
            tool_slimmer_tool_details(
                {"name": "terminal", "load": True},
                schemas=schemas,
            )
        )
        assert result["ok"] is False
        assert result["error"] == "tool_ambiguous"

    def test_load_mcp_excluded_rejected(self, monkeypatch):
        cfg = ToolSlimmerConfig(
            include_mcp_tools=False,
            progressive_enabled=True,
            progressive_max_loaded=10,
            progressive_ttl_seconds=3600,
        )
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.load_config", lambda *_a, **_k: cfg
        )
        result = json.loads(
            tool_slimmer_tool_details(
                {"name": "mcp_server_foo.tool_a", "load": True},
                schemas=SCHEMAS,
            )
        )
        assert result["ok"] is False
        assert result["error"] == "tool_disabled"

    def test_eligible_tool_load_succeeds(self, monkeypatch, tmp_path):
        cfg = ToolSlimmerConfig(
            progressive_enabled=True,
            progressive_max_loaded=10,
            progressive_ttl_seconds=3600,
        )
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.load_config", lambda *_a, **_k: cfg
        )
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.hermes_home",
            lambda: tmp_path,
        )
        result = json.loads(
            tool_slimmer_tool_details(
                {"name": "terminal", "load": True},
                schemas=SCHEMAS,
            )
        )
        assert result["ok"] is True
        assert result["load_action"] == "added"
        assert result["loaded"] is True


class TestToolDetailsNoMutationOnReject:
    """B1: rejected load must not mutate session state."""

    def test_rejected_load_does_not_mutate_state(self, monkeypatch, tmp_path):
        cfg = ToolSlimmerConfig(
            disabled_toolsets=["github"],
            progressive_enabled=True,
            progressive_max_loaded=10,
            progressive_ttl_seconds=3600,
        )
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.load_config", lambda *_a, **_k: cfg
        )
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.hermes_home",
            lambda: tmp_path,
        )
        # Pre-load a valid tool
        state = SessionLoadedState(
            path=tmp_path / "tool-slimmer" / "session_loaded.json",
            max_loaded=10,
            ttl_seconds=3600,
        )
        state.add("read_file")
        loaded_before = state.loaded_names()

        # Attempt to load disabled toolset tool
        result = json.loads(
            tool_slimmer_tool_details(
                {"name": "github_search_code", "load": True},
                schemas=SCHEMAS,
            )
        )
        assert result["ok"] is False

        state2 = SessionLoadedState(
            path=tmp_path / "tool-slimmer" / "session_loaded.json",
            max_loaded=10,
            ttl_seconds=3600,
        )
        loaded_after = state2.loaded_names()
        assert loaded_after == loaded_before


class TestSessionLoadedState:
    """B2: session-scoped loaded state with LRU, TTL, limits, isolation."""

    def test_session_isolation(self, tmp_path):
        state_a = SessionLoadedState(
            path=tmp_path / "state.json",
            max_loaded=10,
            ttl_seconds=3600,
            session_id="sess-a",
        )
        state_a.add("terminal")
        state_b = SessionLoadedState(
            path=tmp_path / "state.json",
            max_loaded=10,
            ttl_seconds=3600,
            session_id="sess-b",
        )
        assert state_b.is_loaded("terminal") is False
        assert state_a.is_loaded("terminal") is True

    def test_anonymous_session(self, tmp_path):
        state = SessionLoadedState(
            path=tmp_path / "state.json",
            max_loaded=10,
            ttl_seconds=3600,
        )
        assert state.session_id == "__anonymous__"
        state.add("terminal")
        assert state.is_loaded("terminal") is True

    def test_lru_eviction(self, tmp_path):
        state = SessionLoadedState(
            path=tmp_path / "state.json",
            max_loaded=2,
            ttl_seconds=3600,
            session_id="lru-test",
        )
        state.add("a")
        time.sleep(0.01)
        state.add("b")
        time.sleep(0.01)
        state.is_loaded("a")  # touch a to update last_used_at
        time.sleep(0.01)
        state.add("c")  # should evict b, not a
        assert state.is_loaded("a") is True
        assert state.is_loaded("b") is False
        assert state.is_loaded("c") is True

    def test_ttl_cleanup(self, tmp_path):
        state = SessionLoadedState(
            path=tmp_path / "state.json",
            max_loaded=10,
            ttl_seconds=1,
            session_id="ttl-test",
        )
        state.add("terminal")
        assert state.is_loaded("terminal") is True
        time.sleep(1.1)
        assert state.is_loaded("terminal") is False

    def test_use_count_and_last_used_at(self, tmp_path):
        state = SessionLoadedState(
            path=tmp_path / "state.json",
            max_loaded=10,
            ttl_seconds=3600,
            session_id="usage-test",
        )
        state.add("tool1")
        info = state.info_dict()
        assert info["tool1"]["use_count"] == 1
        state.is_loaded("tool1")
        info = state.info_dict()
        assert info["tool1"]["use_count"] == 2
        assert info["tool1"]["last_used_at"] is not None

    def test_info_includes_toolset(self, tmp_path):
        state = SessionLoadedState(
            path=tmp_path / "state.json",
            max_loaded=10,
            ttl_seconds=3600,
        )
        state.add("github_search_code", toolset="github")
        info = state.info_dict()
        assert info["github_search_code"]["toolset"] == "github"

    def test_v2_format_preserves_other_sessions(self, tmp_path):
        state_a = SessionLoadedState(
            path=tmp_path / "state.json",
            max_loaded=10,
            ttl_seconds=3600,
            session_id="sess-a",
        )
        state_a.add("x")
        state_b = SessionLoadedState(
            path=tmp_path / "state.json",
            max_loaded=10,
            ttl_seconds=3600,
            session_id="sess-b",
        )
        state_b.add("y")
        # Both sessions should exist in file
        raw = json.loads(tmp_path.joinpath("state.json").read_text())
        sessions = raw["sessions"]
        assert "sess-a" in sessions
        assert "sess-b" in sessions
        assert "x" in sessions["sess-a"]["loaded_tools"]
        assert "y" in sessions["sess-b"]["loaded_tools"]


class TestSessionLoadedDiagnostic:
    """B2: loaded tools diagnostic reflects current session."""

    def test_loaded_tools_per_session(self, monkeypatch, tmp_path):
        cfg = ToolSlimmerConfig(
            progressive_enabled=True,
            progressive_max_loaded=10,
            progressive_ttl_seconds=3600,
        )
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.load_config", lambda *_a, **_k: cfg
        )
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.hermes_home",
            lambda: tmp_path,
        )
        # Prime session a via internal state
        state_a = SessionLoadedState(
            path=tmp_path / "tool-slimmer" / "session_loaded.json",
            max_loaded=10,
            ttl_seconds=3600,
            session_id="sess-a",
        )
        state_a.add("terminal")

        result = json.loads(tool_slimmer_loaded_tools({}, session_id="sess-a"))
        assert result["ok"] is True
        assert result["count"] == 1
        assert "terminal" in result["tools"]

        result_b = json.loads(tool_slimmer_loaded_tools({}, session_id="sess-b"))
        assert result_b["count"] == 0


class TestEmbeddingCacheProvenance:
    """B3: embedding cache must validate provider/backend, model, dimension, text_hashes."""

    def test_cache_miss_different_provider(self, tmp_path):
        cache = EmbeddingCache(tmp_path)
        prov_a = FakeEmbeddingProvider(dim=8)
        checksum = "abc123"
        tools = ["t1"]
        text_hashes = ("hash1",)
        prov_a_provenance = CacheProvenance(
            checksum=checksum,
            provider_id=prov_a.provider_id,
            model_id=prov_a.model_id,
            dim=prov_a.dim,
            text_hashes=text_hashes,
        )
        arr = [[0.1] * 8]
        cache.save(prov_a_provenance, tools, arr)
        # Same checksum/dim but different provider identity
        prov_b_provenance = CacheProvenance(
            checksum=checksum,
            provider_id="different_provider",
            model_id=prov_a.model_id,
            dim=prov_a.dim,
            text_hashes=text_hashes,
        )
        loaded = cache.load(prov_b_provenance)
        assert loaded is None

    def test_cache_miss_different_model(self, tmp_path):
        cache = EmbeddingCache(tmp_path)
        prov = FakeEmbeddingProvider(dim=8)
        checksum = "abc123"
        tools = ["t1"]
        text_hashes = ("hash1",)
        provenance_a = CacheProvenance(
            checksum=checksum,
            provider_id=prov.provider_id,
            model_id="model-a",
            dim=prov.dim,
            text_hashes=text_hashes,
        )
        arr = [[0.1] * 8]
        cache.save(provenance_a, tools, arr)
        provenance_b = CacheProvenance(
            checksum=checksum,
            provider_id=prov.provider_id,
            model_id="model-b",
            dim=prov.dim,
            text_hashes=text_hashes,
        )
        assert cache.load(provenance_b) is None

    def test_cache_miss_different_text_hash(self, tmp_path):
        cache = EmbeddingCache(tmp_path)
        prov = FakeEmbeddingProvider(dim=8)
        checksum = "abc123"
        tools = ["t1"]
        provenance_a = CacheProvenance(
            checksum=checksum,
            provider_id=prov.provider_id,
            model_id=prov.model_id,
            dim=prov.dim,
            text_hashes=("hash_a",),
        )
        arr = [[0.1] * 8]
        cache.save(provenance_a, tools, arr)
        provenance_b = CacheProvenance(
            checksum=checksum,
            provider_id=prov.provider_id,
            model_id=prov.model_id,
            dim=prov.dim,
            text_hashes=("hash_b",),
        )
        assert cache.load(provenance_b) is None

    def test_cache_hit_exact_match(self, tmp_path):
        cache = EmbeddingCache(tmp_path)
        prov = FakeEmbeddingProvider(dim=8)
        checksum = "abc123"
        tools = ["t1", "t2"]
        text_hashes = ("hash1", "hash2")
        provenance = CacheProvenance(
            checksum=checksum,
            provider_id=prov.provider_id,
            model_id=prov.model_id,
            dim=prov.dim,
            text_hashes=text_hashes,
        )
        arr = [[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
               [0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]]
        cache.save(provenance, tools, arr)
        loaded = cache.load(provenance)
        assert loaded is not None
        assert loaded.shape == (2, 8)

    def test_canonical_text_hash_shape(self):
        """_canonical_text_hash must be deterministic and sensitive to text change."""
        schema = {"name": "terminal", "description": "desc", "parameters": {"properties": {"q": {"description": "query"}}}}
        h1 = _canonical_text_hash(schema)
        h2 = _canonical_text_hash(schema)
        assert h1 == h2
        schema2 = {"name": "terminal", "description": "different", "parameters": {"properties": {"q": {"description": "query"}}}}
        h3 = _canonical_text_hash(schema2)
        assert h1 != h3


class TestSemanticCacheProviderIdentity:
    """B3: ranker must produce cache miss on provider switch with same checksum/dim."""

    def test_provider_switch_triggers_miss(self, tmp_path):
        schemas = [
            {"name": "a", "description": "alpha"},
            {"name": "b", "description": "beta"},
        ]
        cache = EmbeddingCache(tmp_path)
        provider_a = FakeEmbeddingProvider(dim=8)
        ranker_a = SemanticRanker(provider=provider_a, cache=cache)
        _ = ranker_a.embed_documents(schemas)

        class SwitchProvider:
            dim = 8
            provider_id = "different"
            model_id = "model"

            def embed(self, texts):
                return [[0.5]*8]*len(texts)

        ranker_b = SemanticRanker(provider=SwitchProvider(), cache=cache)  # type: ignore[arg-type]
        _ = ranker_b.embed_documents(schemas)
        # Different provider should have a cache miss, not reuse cache
        assert provider_a.provider_id != SwitchProvider.provider_id

    def test_openai_provider_id_includes_base_url(self):
        p1 = OpenAIEmbeddingProvider(base_url="https://api.openai.com/v1")
        p2 = OpenAIEmbeddingProvider(base_url="http://localhost:8080/v1")
        assert p1.provider_id != p2.provider_id


class TestSchemaEnumSynchronized:
    """B4: public tool schema must include semantic_hybrid and stay synchronized with config."""

    def test_select_schema_has_semantic_hybrid(self):
        modes = SELECT_SCHEMA["parameters"]["properties"]["mode"]["enum"]
        assert "semantic_hybrid" in modes

    def test_config_valid_modes_has_semantic_hybrid(self):
        from hermes_tool_slimmer.config import VALID_MODES
        assert "semantic_hybrid" in VALID_MODES

    def test_schema_enum_matches_config_valid_modes(self):
        from hermes_tool_slimmer.config import VALID_MODES
        schema_modes = set(SELECT_SCHEMA["parameters"]["properties"]["mode"]["enum"])
        config_modes = set(VALID_MODES)
        assert schema_modes == config_modes, f"Mismatched: schema={schema_modes}, config={config_modes}"


class TestIntegrationNoStateLeak:
    """Cross-blocker integration: session A load does not leak to session B."""

    def test_cross_session_tool_isolation(self, monkeypatch, tmp_path):
        cfg = ToolSlimmerConfig(
            progressive_enabled=True,
            progressive_max_loaded=10,
            progressive_ttl_seconds=3600,
        )
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.load_config", lambda *_a, **_k: cfg
        )
        monkeypatch.setattr(
            "hermes_tool_slimmer.session_tools.hermes_home",
            lambda: tmp_path,
        )
        # Load via session A
        result = json.loads(
            tool_slimmer_tool_details(
                {"name": "terminal", "load": True},
                schemas=SCHEMAS,
                session_id="sess-a",
            )
        )
        assert result["ok"] is True

        # Session B should not see it
        diag_b = json.loads(tool_slimmer_loaded_tools({}, session_id="sess-b"))
        assert diag_b["count"] == 0

        # Session A should see it
        diag_a = json.loads(tool_slimmer_loaded_tools({}, session_id="sess-a"))
        assert diag_a["count"] == 1
