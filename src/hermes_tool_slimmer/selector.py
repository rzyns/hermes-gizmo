from __future__ import annotations

import logging
from collections import defaultdict
from typing import Iterable

from .bm25 import BM25
from .config import ToolSlimmerConfig
from .corpus import build_corpus, tool_name, tool_toolset
from .tokenizer import tokenize
from .toolsets import is_mcp_schema
from .types import Schema, SelectionResult, ToolDocument

LOG = logging.getLogger(__name__)

QUERY_SYNONYMS = {
    "browse": ["browser", "navigate", "url", "web", "website", "page"],
    "browsing": ["browser", "navigate", "url", "web", "website", "page"],
    "site": ["website", "web", "url", "page"],
    "webpage": ["website", "web", "url", "page"],
    "website": ["web", "url", "page"],
}


class ToolSelector:
    def __init__(self, config: ToolSlimmerConfig | None = None) -> None:
        self.config = config or ToolSlimmerConfig()
        self.config.validate()

    def select(self, user_message: str, schemas: list[Schema], **_: object) -> SelectionResult:
        if not self.config.enabled or self.config.mode == "eager":
            return SelectionResult(self.config.mode, schemas, [tool_name(s) for s in schemas], {}, len(schemas), [])
        try:
            return self._select_keyword(user_message, schemas)
        except Exception as exc:
            if self.config.fail_open:
                return SelectionResult(self.config.mode, schemas, [tool_name(s) for s in schemas], {}, len(schemas), [], fail_open=True, reason=str(exc))
            raise

    def _eligible(self, schemas: Iterable[Schema]) -> list[Schema]:
        disabled = set(self.config.disabled_tools)
        disabled_toolsets = set(self.config.disabled_toolsets)
        out = []
        for schema in schemas:
            if not isinstance(schema, dict):
                LOG.warning("skipping non-dict tool schema: %r", schema)
                continue
            name = tool_name(schema)
            toolset = tool_toolset(schema)
            if name in disabled or (toolset and toolset in disabled_toolsets):
                continue
            is_mcp = is_mcp_schema(schema)
            if is_mcp and not self.config.include_mcp_tools:
                continue
            if not is_mcp and not self.config.include_native_tools:
                continue
            out.append(schema)
        return out

    def _select_keyword(self, user_message: str, schemas: list[Schema]) -> SelectionResult:
        eligible = self._eligible(schemas)
        docs = build_corpus(eligible)
        query_tokens = expand_query_tokens(tokenize(user_message))
        bm25 = BM25([doc.tokens for doc in docs])
        raw_scores = bm25.scores(query_tokens)
        scores = {doc.name: score + self._boost(query_tokens, doc) for doc, score in zip(docs, raw_scores, strict=True)}

        schemas_by_name: dict[str, list[Schema]] = defaultdict(list)
        for schema in eligible:
            schemas_by_name[tool_name(schema)].append(schema)
        duplicate_names = sorted(name for name, matches in schemas_by_name.items() if len(matches) > 1)
        if duplicate_names:
            LOG.warning("duplicate tool schema names encountered; first schema wins: %s", ", ".join(duplicate_names))
        by_name = {name: matches[0] for name, matches in schemas_by_name.items()}
        selected: list[Schema] = []
        selected_names: set[str] = set()
        always_present: list[str] = []
        for name in self.config.always_include:
            if name in by_name and name not in selected_names:
                selected.append(by_name[name])
                selected_names.add(name)
                always_present.append(name)

        has_relevant_match = bool(query_tokens) and any(score > 0 for score in scores.values())
        if not has_relevant_match:
            if selected:
                return SelectionResult(self.config.mode, selected, [tool_name(s) for s in selected], scores, len(schemas), always_present, reason="no_relevant_match")
            if eligible and self.config.fail_open:
                return SelectionResult(self.config.mode, eligible, [tool_name(s) for s in eligible], scores, len(schemas), always_present, fail_open=True, reason="no_relevant_match")
            return SelectionResult(self.config.mode, selected, [], scores, len(schemas), always_present, reason="no_relevant_match")

        remaining_slots = self.config.top_k
        ranked = sorted(docs, key=lambda doc: (scores.get(doc.name, 0.0), doc.name), reverse=True)
        for doc in ranked:
            if remaining_slots <= 0:
                break
            if doc.name in selected_names:
                continue
            if scores.get(doc.name, 0.0) <= 0 and selected:
                continue
            selected.append(by_name[doc.name])
            selected_names.add(doc.name)
            remaining_slots -= 1

        if not selected and eligible and self.config.fail_open:
            return SelectionResult(self.config.mode, schemas, [tool_name(s) for s in schemas], scores, len(schemas), always_present, fail_open=True, reason="selector produced empty set")
        return SelectionResult(self.config.mode, selected, [tool_name(s) for s in selected], scores, len(schemas), always_present)

    @staticmethod
    def _boost(query_tokens: list[str], doc: ToolDocument) -> float:
        query = set(query_tokens)
        boost = 0.0
        normalized_name = doc.name.lower()
        if normalized_name in " ".join(query_tokens) or normalized_name.replace("_", " ") in " ".join(query_tokens):
            boost += 10.0
        if doc.toolset and set(tokenize(doc.toolset)) & query:
            boost += 2.5
        boost += 1.25 * len(doc.parameter_tokens & query)
        return boost


def expand_query_tokens(tokens: list[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        for value in [token, *QUERY_SYNONYMS.get(token, [])]:
            if value not in seen:
                expanded.append(value)
                seen.add(value)
    return expanded


def select_schemas(user_message: str, schemas: list[Schema], config: ToolSlimmerConfig | None = None, **kwargs: object) -> list[Schema]:
    return ToolSelector(config).select(user_message, schemas, **kwargs).selected
