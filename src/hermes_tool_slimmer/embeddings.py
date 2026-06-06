from __future__ import annotations

import hashlib
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import numpy as np
except Exception:
    np = None  # type: ignore[assignment]

from .config import hermes_home
from .corpus import tool_description, tool_name
from .index_store import IndexStore
from .types import Schema

LOG = logging.getLogger(__name__)


def _ensure_numpy() -> Any:
    if np is None:
        raise ImportError(
            "numpy is required for semantic_hybrid mode. Install with: pip install hermes-tool-slimmer[semantic]"
        )
    return np


class EmbeddingProvider(ABC):
    """Abstract base for text→embedding providers."""

    @property
    @abstractmethod
    def dim(self) -> int:
        """Embedding dimensionality."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return a list of float vectors, one per text."""

    @property
    def provider_id(self) -> str:
        """Canonical provider/backend identifier for cache provenance.

        Must uniquely distinguish the backend (e.g. ``openai``, ``fake``, ``ollama``).
        """
        return "unknown"

    @property
    def model_id(self) -> str:
        """Canonical model identifier for cache provenance."""
        return "unknown"


@dataclass(frozen=True)
class _CacheKey:
    """Internal cache key combining provenance and content identity."""

    checksum: str
    provider: str
    model: str
    dim: int


def _stable_hash(text: str, dim: int) -> list[float]:
    """Deterministic fake embedding via SHA-256 hashing."""
    _ensure_numpy()
    raw = hashlib.sha256(text.encode("utf-8")).digest()
    floats: list[float] = []
    idx = 0
    while len(floats) < dim:
        chunk = raw[idx % len(raw) : (idx % len(raw)) + 4]
        if len(chunk) < 4:
            raw = hashlib.sha256(raw).digest()
            idx = 0
            continue
        val = int.from_bytes(chunk, "big", signed=True)
        floats.append(val / 2 ** 31)
        idx += 4
    arr = np.array(floats, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return arr.tolist()


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic fake embedding backend for tests and offline use.

    Produces unit-norm vectors derived from deterministic SHA-256 hashing so
    cosine similarity between any two texts is reproducible across runs.
    """

    def __init__(self, dim: int = 128):
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def provider_id(self) -> str:
        return "fake"

    @property
    def model_id(self) -> str:
        return f"stable_hash_dim{self._dim}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_stable_hash(text, self._dim) for text in texts]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible HTTP embedding provider.

    Configurable base URL, model name, and timeout. No secrets are baked in;
    the caller must ensure the API key is available in the environment.
    Raises on failure so the selector can degrade gracefully.
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
        timeout: float = 30.0,
        dim: int | None = None,
    ) -> None:
        self.model = model
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout = timeout
        self._dim = dim or 1536

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def provider_id(self) -> str:
        return f"openai:{self.base_url}"

    @property
    def model_id(self) -> str:
        return self.model

    def embed(self, texts: list[str]) -> list[list[float]]:
        import urllib.request
        import urllib.error

        api_key = os.environ.get("OPENAI_API_KEY") or ""
        if not api_key:
            raise RuntimeError("OpenAIEmbeddingProvider requires OPENAI_API_KEY environment variable")

        payload = json.dumps({"input": texts, "model": self.model, "encoding_format": "float"}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Embedding API HTTP {exc.code}: {body}") from exc
        except Exception as exc:
            raise RuntimeError(f"Embedding API request failed: {exc}") from exc

        items = data.get("data", [])
        if len(items) != len(texts):
            raise RuntimeError(f"Embedding API returned {len(items)} items for {len(texts)} texts")
        vectors: list[list[float]] = []
        for item in items:
            vec = item.get("embedding")
            if not isinstance(vec, list):
                raise RuntimeError(f"Embedding API item missing embedding: {item!r}")
            vectors.append([float(v) for v in vec])
        if vectors:
            first_len = len(vectors[0])
            if any(len(v) != first_len for v in vectors):
                raise RuntimeError("Embedding API returned inconsistent vector lengths")
            self._dim = first_len
        return vectors


def _canonical_text_hash(schema: Schema) -> str:
    """Return a deterministic hash of the canonical embedding text for a schema."""
    name = tool_name(schema)
    desc = tool_description(schema)
    params = schema.get("parameters") or schema.get("input_schema") or {}
    parts: list[str] = [name, desc]
    if isinstance(params, dict):
        props = params.get("properties") or {}
        if isinstance(props, dict):
            for key in sorted(props.keys()):
                parts.append(key)
                spec = props[key]
                if isinstance(spec, dict):
                    parts.append(str(spec.get("description") or ""))
    text = "\n".join(filter(None, parts))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class CacheProvenance:
    """Identity tuple used to distinguish cache entries across backend/model changes."""

    checksum: str
    provider_id: str
    model_id: str
    dim: int
    text_hashes: tuple[str, ...]

    @property
    def cache_key(self) -> str:
        """Stable string key for filesystem naming."""
        payload = json.dumps({
            "checksum": self.checksum,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "dim": self.dim,
            "text_hashes": list(self.text_hashes),
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass
class EmbeddingCache:
    """JSON/NPZ on-disk cache for schema embeddings keyed by provenance.

    Layout under root (default ``~/.hermes/tool-slimmer/semantic_cache``):

    * ``{cache_key}.npz`` — NumPy archive with an ``embeddings`` float32 array
      of shape ``(n_tools, dim)``.
    * ``{cache_key}.json`` — metadata mapping tool names to row indices plus
      provider/model identity, dimension, and canonical text hashes.
    """

    root: Path

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or hermes_home() / "tool-slimmer" / "semantic_cache").expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def _npz_path(self, cache_key: str) -> Path:
        return self.root / f"{cache_key}.npz"

    def _json_path(self, cache_key: str) -> Path:
        return self.root / f"{cache_key}.json"

    def _build_meta(self, provenance: CacheProvenance, tools: list[str]) -> dict[str, Any]:
        return {
            "tools": tools,
            "dim": provenance.dim,
            "provider_id": provenance.provider_id,
            "model_id": provenance.model_id,
            "text_hashes": list(provenance.text_hashes),
            "checksum": provenance.checksum,
        }

    def _validate_meta(self, meta: dict[str, Any], expected: CacheProvenance) -> bool:
        if meta.get("checksum") != expected.checksum:
            return False
        if meta.get("dim") != expected.dim:
            return False
        if meta.get("provider_id") != expected.provider_id:
            return False
        if meta.get("model_id") != expected.model_id:
            return False
        stored_hashes = meta.get("text_hashes")
        if not isinstance(stored_hashes, list) or tuple(stored_hashes) != expected.text_hashes:
            return False
        return True

    def load(self, arg: CacheProvenance | str, expected_tools: list[str] | None = None, expected_dim: int | None = None) -> Any | None:
        """Load cached embeddings if provenance matches.

        Supports two signatures:
        * ``load(provenance: CacheProvenance)`` — full provider/model/dim/hash validation.
        * ``load(checksum: str, expected_tools: list[str], expected_dim: int)`` — backward-compatible
          checksum/tools/dim validation without provider identity.
        """
        if isinstance(arg, CacheProvenance):
            return self._load_provenance(arg)
        if isinstance(arg, str) and expected_tools is not None and expected_dim is not None:
            return self._load_legacy(arg, expected_tools, expected_dim)
        return None

    def _load_legacy(self, checksum: str, expected_tools: list[str], expected_dim: int) -> Any | None:
        """Backward-compatible load using raw checksum as filename."""
        np = _ensure_numpy()
        meta_path = self._json_path(checksum)
        npz_path = self._npz_path(checksum)
        if not meta_path.exists() or not npz_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        tools = meta.get("tools")
        dim = meta.get("dim")
        if not isinstance(tools, list) or tools != expected_tools:
            return None
        if not isinstance(dim, int) or dim != expected_dim:
            return None
        try:
            loaded = np.load(npz_path)  # type: ignore[arg-type]
            arr = loaded["embeddings"]
        except (OSError, KeyError):
            return None
        if not isinstance(arr, np.ndarray):
            return None
        if arr.shape != (len(expected_tools), expected_dim):
            return None
        return arr.astype(np.float32)

    def _load_provenance(self, provenance: CacheProvenance) -> Any | None:
        """Load cached embeddings if all provenance fields match."""
        np = _ensure_numpy()
        cache_key = provenance.cache_key
        meta_path = self._json_path(cache_key)
        npz_path = self._npz_path(cache_key)
        if not meta_path.exists() or not npz_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(meta, dict):
            return None
        if not self._validate_meta(meta, provenance):
            return None
        try:
            loaded = np.load(npz_path)  # type: ignore[arg-type]
            arr = loaded["embeddings"]
        except (OSError, KeyError):
            return None
        if not isinstance(arr, np.ndarray):
            return None
        if arr.shape != (len(provenance.text_hashes), provenance.dim):
            return None
        return arr.astype(np.float32)

    def save(self, arg: CacheProvenance | str, tools: list[str], embeddings: Any) -> None:
        """Persist embeddings matrix and metadata.

        Supports two signatures:
        * ``save(provenance: CacheProvenance, tools, embeddings)`` — full provenance-aware.
        * ``save(checksum: str, tools, embeddings)`` — backward-compatible checksum-only.
        """
        if isinstance(arg, CacheProvenance):
            self._save_provenance(arg, tools, embeddings)
            return
        if isinstance(arg, str):
            self._save_legacy(arg, tools, embeddings)
            return

    def _save_legacy(self, checksum: str, tools: list[str], embeddings: Any) -> None:
        """Backward-compatible save using raw checksum as filename."""
        np = _ensure_numpy()
        arr = np.array(embeddings, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"Expected 2-D embeddings array, got shape {arr.shape}")
        meta = {"tools": tools, "dim": arr.shape[1]}
        np.savez(self._npz_path(checksum), embeddings=arr)
        self._json_path(checksum).write_text(json.dumps(meta, indent=2))

    def _save_provenance(self, provenance: CacheProvenance, tools: list[str], embeddings: Any) -> None:
        """Persist embeddings matrix and metadata for provenance."""
        np = _ensure_numpy()
        arr = np.array(embeddings, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"Expected 2-D embeddings array, got shape {arr.shape}")
        if arr.shape != (len(tools), provenance.dim):
            raise ValueError(
                f"Shape/tools mismatch: expected ({len(tools)}, {provenance.dim}), got {arr.shape}"
            )
        cache_key = provenance.cache_key
        meta = self._build_meta(provenance, tools)
        np.savez(self._npz_path(cache_key), embeddings=arr)
        self._json_path(cache_key).write_text(json.dumps(meta, indent=2))

    def clear(self, arg: CacheProvenance | str | None = None) -> None:
        """Remove cached files.

        Supports ``clear()`` (all), ``clear(provenance)`` (new API), or ``clear(checksum)`` (legacy).
        """
        if arg is None:
            for path in self.root.glob("*.npz"):
                path.unlink(missing_ok=True)
            for path in self.root.glob("*.json"):
                path.unlink(missing_ok=True)
            return
        if isinstance(arg, CacheProvenance):
            cache_key = arg.cache_key
            self._npz_path(cache_key).unlink(missing_ok=True)
            self._json_path(cache_key).unlink(missing_ok=True)
            return
        if isinstance(arg, str):
            self._npz_path(arg).unlink(missing_ok=True)
            self._json_path(arg).unlink(missing_ok=True)
            return


class SemanticRanker:
    """Orchestrates embedding lookup/computation and semantic scoring."""

    def __init__(
        self,
        provider: EmbeddingProvider | None = None,
        cache: EmbeddingCache | None = None,
    ) -> None:
        self.provider = provider or FakeEmbeddingProvider()
        self.cache = cache or EmbeddingCache()

    def _document_text(self, schema: Schema) -> str:
        """Flatten a schema into a single string for embedding."""
        name = tool_name(schema)
        desc = tool_description(schema)
        parts = [name, desc]
        params = schema.get("parameters") or schema.get("input_schema") or {}
        if isinstance(params, dict):
            props = params.get("properties") or {}
            if isinstance(props, dict):
                for key, spec in props.items():
                    parts.append(key)
                    if isinstance(spec, dict):
                        parts.append(str(spec.get("description") or ""))
        return " ".join(filter(None, parts))

    def embed_documents(self, schemas: list[Schema]) -> Any:
        """Return document embedding matrix for schemas, using cache if possible."""
        np = _ensure_numpy()
        checksum = IndexStore.checksum(schemas)
        tool_names = [tool_name(s) for s in schemas]
        text_hashes = [_canonical_text_hash(s) for s in schemas]
        provenance = CacheProvenance(
            checksum=checksum,
            provider_id=self.provider.provider_id,
            model_id=self.provider.model_id,
            dim=self.provider.dim,
            text_hashes=tuple(text_hashes),
        )
        cached = self.cache.load(provenance)
        if cached is not None:
            LOG.debug("Semantic cache hit for %s (%d docs)", checksum[:16], len(schemas))
            return cached

        texts = [self._document_text(s) for s in schemas]
        vectors = self.provider.embed(texts)
        arr = np.array(vectors, dtype=np.float32)
        self.cache.save(provenance, tool_names, arr)
        return arr

    def embed_query(self, query: str) -> Any:
        """Return a single query embedding vector."""
        np = _ensure_numpy()
        vectors = self.provider.embed([query])
        return np.array(vectors[0], dtype=np.float32)

    def cosine_similarities(self, query_vec: Any, doc_matrix: Any) -> Any:
        """Return 1-D array of cosine similarities."""
        np = _ensure_numpy()
        query_norm = np.linalg.norm(query_vec)
        doc_norms = np.linalg.norm(doc_matrix, axis=1)
        if query_norm == 0:
            return np.zeros(len(doc_matrix), dtype=np.float32)
        safe_norms = np.where(doc_norms == 0, 1.0, doc_norms)
        sims = (doc_matrix @ query_vec) / safe_norms / query_norm
        return np.nan_to_num(sims, nan=0.0, posinf=0.0, neginf=0.0)


class ReciprocalRankFusion:
    """Combine multiple ranked lists with Reciprocal Rank Fusion.

    Each scorer produces a ``list[float]`` aligned with the document list.
    We rank by each scorer independently, then sum ``1 / (rrf_k + rank)``.
    """

    def __init__(self, rrf_k: float = 60.0) -> None:
        if rrf_k <= 0:
            raise ValueError("rrf_k must be > 0")
        self.rrf_k = rrf_k

    def fuse(
        self,
        bm25_scores: list[float],
        semantic_scores: list[float],
    ) -> tuple[list[float], dict[str, list[float]]]:
        """Return combined RRF scores and per-source score details.

        Output tuple: ``(combined_scores, details)`` where ``details`` is a
        dict mapping detail keys to lists of float values aligned with docs.
        """
        _ensure_numpy()

        def _ranks(scores: list[float]) -> list[int]:
            """0-based rank: highest score gets rank 0."""
            order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            ranks = [0] * len(scores)
            for rank, idx in enumerate(order):
                ranks[idx] = rank
            return ranks

        bm25_ranks = _ranks(bm25_scores)
        sem_ranks = _ranks(semantic_scores)

        combined: list[float] = []
        for i in range(len(bm25_scores)):
            score = (1.0 / (self.rrf_k + bm25_ranks[i] + 1)) + (1.0 / (self.rrf_k + sem_ranks[i] + 1))
            combined.append(score)

        details = {
            "rrf": combined,
            "bm25_rank": [float(rank) for rank in bm25_ranks],
            "semantic_rank": [float(rank) for rank in sem_ranks],
            "cosine_similarity": semantic_scores,
        }
        return combined, details
