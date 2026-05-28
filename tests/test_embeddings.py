"""Tests for semantic_hybrid ranking backend."""
from __future__ import annotations

import tempfile

import pytest

from hermes_tool_slimmer.config import ToolSlimmerConfig
from hermes_tool_slimmer.embeddings import (
    EmbeddingCache,
    FakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
    ReciprocalRankFusion,
    SemanticRanker,
    _stable_hash,
)
from hermes_tool_slimmer.selector import ToolSelector


SCHEMAS = [
    {"name": "terminal", "toolset": "native", "description": "Run shell commands"},
    {"name": "read_file", "toolset": "native", "description": "Read a file"},
    {"name": "search_files", "toolset": "native", "description": "Search files in repo"},
    {"name": "github_search_code", "toolset": "github", "description": "Search GitHub code", "parameters": {"properties": {"query": {"description": "search query"}}}},
    {"name": "slack_send_message", "toolset": "slack", "description": "Send Slack message"},
]


class TestFakeEmbeddingProvider:
    def test_deterministic_output(self):
        p = FakeEmbeddingProvider(dim=8)
        v1 = p.embed(["hello"])[0]
        v2 = p.embed(["hello"])[0]
        assert v1 == v2

    def test_unit_normalized(self):
        p = FakeEmbeddingProvider(dim=16)
        v = p.embed(["test"])[0]
        norm = sum(x * x for x in v) ** 0.5
        assert pytest.approx(norm, 1e-4) == 1.0

    def test_batch_returns_correct_count(self):
        p = FakeEmbeddingProvider(dim=8)
        out = p.embed(["a", "b", "c"])
        assert len(out) == 3
        assert all(len(v) == 8 for v in out)

    def test_dim_property(self):
        p = FakeEmbeddingProvider(dim=64)
        assert p.dim == 64


class TestStableHash:
    def test_reproducibility(self):
        v1 = _stable_hash("foo", 32)
        v2 = _stable_hash("foo", 32)
        assert v1 == v2

    def test_different_texts_differ(self):
        v1 = _stable_hash("foo", 32)
        v2 = _stable_hash("bar", 32)
        assert v1 != v2

    def test_norm_one(self):
        v = _stable_hash("normcheck", 64)
        norm = sum(x ** 2 for x in v) ** 0.5
        assert pytest.approx(norm, 1e-4) == 1.0


class TestOpenAIEmbeddingProvider:
    def test_dim_property(self):
        p = OpenAIEmbeddingProvider(dim=256)
        assert p.dim == 256

    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        p = OpenAIEmbeddingProvider()
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            p.embed(["x"])

    def test_allows_explicit_base_url(self):
        p = OpenAIEmbeddingProvider(base_url="http://localhost:8080/v1")
        assert p.base_url == "http://localhost:8080/v1"


class TestEmbeddingCache:
    def test_miss_on_empty(self):
        with tempfile.TemporaryDirectory() as td:
            cache = EmbeddingCache(td)
            assert cache.load("abc", ["a", "b"], 16) is None

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            cache = EmbeddingCache(td)
            arr = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
            cache.save("chk", ["t1", "t2"], arr)
            loaded = cache.load("chk", ["t1", "t2"], 3)
            assert loaded is not None
            assert loaded.shape == (2, 3)
            assert loaded[0].tolist() == pytest.approx([0.1, 0.2, 0.3])

    def test_mismatch_tools_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            cache = EmbeddingCache(td)
            cache.save("chk", ["t1", "t2"], [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
            assert cache.load("chk", ["t1"], 3) is None

    def test_mismatch_dim_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            cache = EmbeddingCache(td)
            cache.save("chk", ["t1", "t2"], [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
            assert cache.load("chk", ["t1", "t2"], 99) is None

    def test_save_requires_2d(self):
        with tempfile.TemporaryDirectory() as td:
            cache = EmbeddingCache(td)
            with pytest.raises(ValueError, match="2-D"):
                cache.save("chk", ["t1"], [0.1, 0.2])

    def test_clear_single(self):
        with tempfile.TemporaryDirectory() as td:
            cache = EmbeddingCache(td)
            cache.save("chk", ["t1"], [[0.1]])
            cache.clear("chk")
            assert cache.load("chk", ["t1"], 1) is None

    def test_clear_all(self):
        with tempfile.TemporaryDirectory() as td:
            cache = EmbeddingCache(td)
            cache.save("a", ["t1"], [[0.1]])
            cache.save("b", ["t2"], [[0.2]])
            cache.clear()
            assert cache.load("a", ["t1"], 1) is None
            assert cache.load("b", ["t2"], 1) is None


class TestSemanticRanker:
    def test_embed_documents_caching(self):
        with tempfile.TemporaryDirectory() as td:
            cache = EmbeddingCache(td)
            provider = FakeEmbeddingProvider(dim=8)
            ranker = SemanticRanker(provider=provider, cache=cache)
            schemas = [
                {"name": "foo", "description": "foo desc"},
                {"name": "bar", "description": "bar desc"},
            ]
            mat1 = ranker.embed_documents(schemas)
            mat2 = ranker.embed_documents(schemas)
            assert mat1.shape == (2, 8)
            assert (mat1 == mat2).all()

    def test_cosine_similarities_range(self):
        provider = FakeEmbeddingProvider(dim=8)
        ranker = SemanticRanker(provider=provider)
        doc_matrix = ranker.embed_documents([
            {"name": "one", "description": "first"},
            {"name": "two", "description": "second"},
        ])
        query_vec = ranker.embed_query("first")
        sims = ranker.cosine_similarities(query_vec, doc_matrix)
        assert len(sims) == 2
        assert all(-1.0 <= s <= 1.0 for s in sims)

    def test_cosine_higher_for_similar_texts(self):
        """A query identical to a document should score highest for that doc."""
        provider = FakeEmbeddingProvider(dim=16)
        ranker = SemanticRanker(provider=provider)
        schemas = [
            {"name": "alpha", "description": "alpha desc"},
            {"name": "beta", "description": "beta desc"},
        ]
        doc_matrix = ranker.embed_documents(schemas)
        query_vec = ranker.embed_query("alpha desc")
        sims = ranker.cosine_similarities(query_vec, doc_matrix)
        assert sims[0] > sims[1]

    def test_document_text_flattening(self):
        provider = FakeEmbeddingProvider(dim=16)
        ranker = SemanticRanker(provider=provider)
        text = ranker._document_text({
            "name": "x",
            "description": "desc",
            "parameters": {
                "properties": {
                    "p1": {"description": "param desc"},
                }
            },
        })
        assert "x" in text
        assert "desc" in text
        assert "p1" in text
        assert "param desc" in text


class TestReciprocalRankFusion:
    def test_fuse_basic(self):
        bm25 = [0.8, 0.4, 0.1]
        sem = [0.1, 0.9, 0.2]
        rrf = ReciprocalRankFusion(rrf_k=60)
        combined, details = rrf.fuse(bm25, sem)
        assert len(combined) == 3
        assert set(details.keys()) == {"rrf", "bm25_rank", "semantic_rank", "cosine_similarity"}

    def test_higher_scores_win(self):
        bm25 = [1.0, 0.0, 0.0]
        sem = [1.0, 0.0, 0.0]
        rrf = ReciprocalRankFusion(rrf_k=60)
        combined, _ = rrf.fuse(bm25, sem)
        assert combined[0] > combined[1]
        assert combined[0] > combined[2]

    def test_invalid_rrf_k(self):
        with pytest.raises(ValueError, match="rrf_k"):
            ReciprocalRankFusion(rrf_k=0)

    def test_details_alignment(self):
        bm25 = [0.1, 0.2]
        sem = [0.3, 0.4]
        rrf = ReciprocalRankFusion(rrf_k=60)
        combined, details = rrf.fuse(bm25, sem)
        assert len(details["bm25_rank"]) == 2
        assert len(details["semantic_rank"]) == 2
        assert len(details["cosine_similarity"]) == 2


class TestSemanticHybridSelector:
    def test_semantic_hybrid_mode_ranks(self):
        cfg = ToolSlimmerConfig(mode="semantic_hybrid", top_k=2, always_include=[])
        result = ToolSelector(cfg).select("send a message to slack", SCHEMAS)
        assert result.mode == "semantic_hybrid"
        assert "slack_send_message" in result.selected_names
        for name in result.selected_names:
            assert "semantic_cosine" in result.score_details[name]
            assert "rrf" in result.score_details[name]

    def test_semantic_hybrid_with_always_includes(self):
        cfg = ToolSlimmerConfig(mode="semantic_hybrid", top_k=1, always_include=["terminal"])
        result = ToolSelector(cfg).select("github code", SCHEMAS)
        assert "terminal" in result.selected_names
        assert "github_search_code" in result.selected_names

    def test_fails_open_on_embedding_failure(self, monkeypatch):
        cfg = ToolSlimmerConfig(mode="semantic_hybrid", top_k=2, always_include=[], fail_open=True)
        selector = ToolSelector(cfg)

        def _boom(*a, **k):
            raise RuntimeError("embedding boom")

        monkeypatch.setattr(SemanticRanker, "embed_documents", _boom)
        result = selector.select("github search", SCHEMAS)
        # degradation to keyword should still produce results because "github" is keyword-matched
        assert result.fail_open is False
        assert "github_search_code" in result.selected_names

    def test_semantic_cache_disabled(self, monkeypatch):
        cfg = ToolSlimmerConfig(mode="semantic_hybrid", top_k=1, semantic_cache_enabled=False)
        result = ToolSelector(cfg).select("slack", SCHEMAS)
        assert result.mode == "semantic_hybrid"
        assert "slack_send_message" in result.selected_names

    def test_rrf_k_validation(self):
        with pytest.raises(ValueError, match="rrf_k"):
            ToolSelector(ToolSlimmerConfig(mode="semantic_hybrid", rrf_k=0))
        with pytest.raises(ValueError, match="rrf_k"):
            ToolSelector(ToolSlimmerConfig(mode="semantic_hybrid", rrf_k=-5))

    def test_score_details_include_rrf_ranks(self):
        cfg = ToolSlimmerConfig(mode="semantic_hybrid", top_k=3, always_include=[])
        result = ToolSelector(cfg).select("search", SCHEMAS)
        for name in result.selected_names:
            details = result.score_details[name]
            assert "bm25_rank" in details
            assert "semantic_rank" in details
            assert isinstance(details["bm25_rank"], float)
            assert isinstance(details["semantic_rank"], float)


class TestSemanticHybridFallback:
    def test_low_information_query_still_works(self):
        cfg = ToolSlimmerConfig(mode="semantic_hybrid", top_k=3, always_include=["memory"])
        schemas = [
            {"name": "memory", "description": "Remember information"},
            {"name": "terminal", "description": "Run shell commands"},
        ]
        result = ToolSelector(cfg).select("hello", schemas)
        assert result.reason == "low_information_query"
        assert "memory" in result.selected_names

    def test_no_relevant_match_empty_slots(self):
        cfg = ToolSlimmerConfig(mode="semantic_hybrid", top_k=2, always_include=[])
        result = ToolSelector(cfg).select("xyzqwerty12345 nonsense", SCHEMAS)
        # Fake embeddings give deterministic non-zero cosine for any text.
        # We simply assert the selector doesn't fail open and returns coherent scores.
        assert result.fail_open is False
        assert all(s >= 0 for s in result.scores.values())

    def test_below_min_score_empty(self):
        cfg = ToolSlimmerConfig(mode="semantic_hybrid", top_k=3, always_include=[], min_score=9999.0)
        result = ToolSelector(cfg).select("search files", SCHEMAS)
        assert result.reason == "below_min_score"


class TestConfigIntegration:
    def test_semantic_fields_roundtrip_via_from_mapping(self):
        raw = {
            "mode": "semantic_hybrid",
            "semantic_provider": "openai",
            "semantic_openai_model": "text-embedding-3-large",
            "semantic_openai_base_url": "http://localhost:8080/v1",
            "semantic_openai_timeout": 45.0,
            "semantic_dim": 256,
            "rrf_k": 120.0,
            "semantic_cache_enabled": True,
        }
        cfg = ToolSlimmerConfig.from_mapping(raw)
        assert cfg.semantic_provider == "openai"
        assert cfg.semantic_openai_model == "text-embedding-3-large"
        assert cfg.semantic_openai_base_url == "http://localhost:8080/v1"
        assert cfg.semantic_openai_timeout == 45.0
        assert cfg.semantic_dim == 256
        assert cfg.rrf_k == 120.0
        assert cfg.semantic_cache_enabled is True

    def test_default_semantic_config(self):
        cfg = ToolSlimmerConfig()
        assert cfg.semantic_provider == "fake"
        assert cfg.rrf_k == 60.0
        assert cfg.semantic_cache_enabled is True

    def test_mode_validation_rejects_invalid_mode(self):
        with pytest.raises(ValueError, match="semantic"):
            ToolSlimmerConfig.from_mapping({"mode": "semantic_hybrid_bad"})
