from __future__ import annotations

import logging
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Iterable

from .bm25 import BM25
from .config import ToolSlimmerConfig
from .corpus import build_corpus, tool_name, tool_toolset
from .tokenizer import tokenize
from .toolsets import is_mcp_schema
from .types import Schema, SelectionResult, ToolDocument

LOG = logging.getLogger(__name__)

BUILTIN_ALIASES = {
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
        base_query_tokens = tokenize(user_message)
        query_tokens, alias_terms = expand_query_tokens(base_query_tokens, self.config.aliases)
        bm25 = BM25([doc.tokens for doc in docs])
        raw_scores = bm25.scores(query_tokens)
        score_details: dict[str, dict[str, float]] = {}
        scores: dict[str, float] = {}
        for doc, raw_score in zip(docs, raw_scores, strict=True):
            parts = self._score_parts(query_tokens, alias_terms, doc, hybrid=self.config.mode == "hybrid")
            parts["bm25"] = raw_score
            total = round(sum(parts.values()), 6)
            parts["total"] = total
            score_details[doc.name] = parts
            scores[doc.name] = total

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
                return SelectionResult(self.config.mode, selected, [tool_name(s) for s in selected], scores, len(schemas), always_present, reason="no_relevant_match", score_details=score_details, expanded_query_tokens=query_tokens)
            if eligible and self.config.fail_open and self.config.top_k > 0:
                return SelectionResult(self.config.mode, eligible, [tool_name(s) for s in eligible], scores, len(schemas), always_present, fail_open=True, reason="no_relevant_match", score_details=score_details, expanded_query_tokens=query_tokens)
            return SelectionResult(self.config.mode, selected, [], scores, len(schemas), always_present, reason="no_relevant_match", score_details=score_details, expanded_query_tokens=query_tokens)

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

        if not selected and eligible and self.config.fail_open and self.config.top_k > 0:
            return SelectionResult(self.config.mode, schemas, [tool_name(s) for s in schemas], scores, len(schemas), always_present, fail_open=True, reason="selector produced empty set", score_details=score_details, expanded_query_tokens=query_tokens)
        return SelectionResult(self.config.mode, selected, [tool_name(s) for s in selected], scores, len(schemas), always_present, score_details=score_details, expanded_query_tokens=query_tokens)

    @staticmethod
    def _score_parts(query_tokens: list[str], alias_terms: set[str], doc: ToolDocument, *, hybrid: bool = False) -> dict[str, float]:
        query = set(query_tokens)
        parts = {"name_boost": 0.0, "toolset_boost": 0.0, "parameter_boost": 0.0, "alias_boost": 0.0, "hybrid_boost": 0.0}
        normalized_name = doc.name.lower()
        query_text = " ".join(query_tokens)
        if len(normalized_name) >= 2 and (normalized_name in query_text or normalized_name.replace("_", " ") in query_text):
            parts["name_boost"] += 10.0
        if doc.toolset and set(tokenize(doc.toolset)) & query:
            parts["toolset_boost"] += 2.5
        parts["parameter_boost"] += 1.25 * len(doc.parameter_tokens & query)
        alias_matches = alias_terms & (set(doc.tokens) | doc.parameter_tokens | set(tokenize(doc.toolset or "")))
        parts["alias_boost"] += 0.75 * len(alias_matches)
        if hybrid:
            doc_terms = {token for token in doc.tokens if len(token) >= 4}
            for token in query:
                if len(token) < 4 or token in doc_terms:
                    continue
                if any(SequenceMatcher(None, token, candidate).ratio() >= 0.84 for candidate in doc_terms):
                    parts["hybrid_boost"] += 0.5
        return parts


def expand_query_tokens(tokens: list[str], configured_aliases: dict[str, list[str]] | None = None) -> tuple[list[str], set[str]]:
    aliases = {key: list(values) for key, values in BUILTIN_ALIASES.items()}
    for key, values in (configured_aliases or {}).items():
        aliases.setdefault(str(key).lower(), [])
        aliases[str(key).lower()].extend(str(value).lower() for value in values)
    expanded: list[str] = []
    seen: set[str] = set()
    alias_terms: set[str] = set()
    for token in tokens:
        token_aliases = aliases.get(token, [])
        alias_terms.update(token_aliases)
        for value in [token, *token_aliases]:
            if value not in seen:
                expanded.append(value)
                seen.add(value)
    return expanded, alias_terms


def select_schemas(user_message: str, schemas: list[Schema], config: ToolSlimmerConfig | None = None, **kwargs: object) -> list[Schema]:
    return ToolSelector(config).select(user_message, schemas, **kwargs).selected
