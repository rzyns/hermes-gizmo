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


def _stable_hash(text: str, dim: int) -> list[float]:
    """Deterministic fake embedding via SHA-256 hashing."""
    _ensure_numpy()
    raw = hashlib.sha256(text.encode("utf-8")).digest()
    floats = []
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


@dataclass
class EmbeddingCache:
    """JSON/NPZ on-disk cache for schema embeddings keyed by checksum.

    Layout under root (default ``~/.hermes/tool-slimmer/semantic_cache``):

    * ``{checksum}.npz`` — NumPy archive with an ``embeddings`` float32 array
      of shape ``(n_tools, dim)``.
    * ``{checksum}.json`` — metadata mapping tool names to row indices plus
      provider model/dim for cache invalidation hints.
    """

    root: Path

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or hermes_home() / "tool-slimmer" / "semantic_cache").expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def _npz_path(self, checksum: str) -> Path:
        return self.root / f"{checksum}.npz"

    def _json_path(self, checksum: str) -> Path:
        return self.root / f"{checksum}.json"

    def load(self, checksum: str, expected_tools: list[str], expected_dim: int) -> Any | None:
        """Load cached embeddings if checksum, tools, and dim match.

        Returns a numpy array or None on any mismatch / corruption.
        """
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

    def save(self, checksum: str, tools: list[str], embeddings: Any) -> None:
        """Persist embeddings matrix and metadata for checksum."""
        np = _ensure_numpy()
        arr = np.array(embeddings, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"Expected 2-D embeddings array, got shape {arr.shape}")
        meta = {"tools": tools, "dim": arr.shape[1]}
        np.savez(self._npz_path(checksum), embeddings=arr)
        self._json_path(checksum).write_text(json.dumps(meta, indent=2))

    def clear(self, checksum: str | None = None) -> None:
        """Remove cached files for a checksum, or the entire cache if None."""
        if checksum is None:
            for path in self.root.glob("*.npz"):
                path.unlink(missing_ok=True)
            for path in self.root.glob("*.json"):
                path.unlink(missing_ok=True)
            return
        self._npz_path(checksum).unlink(missing_ok=True)
        self._json_path(checksum).unlink(missing_ok=True)


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
        cached = self.cache.load(checksum, tool_names, self.provider.dim)
        if cached is not None:
            LOG.debug("Semantic cache hit for %s (%d docs)", checksum[:16], len(schemas))
            return cached

        texts = [self._document_text(s) for s in schemas]
        vectors = self.provider.embed(texts)
        arr = np.array(vectors, dtype=np.float32)
        self.cache.save(checksum, tool_names, arr)
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
            "bm25_rank": bm25_ranks,
            "semantic_rank": sem_ranks,
            "cosine_similarity": semantic_scores,
        }
        return combined, details
