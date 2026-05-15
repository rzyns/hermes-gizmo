from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .tokenizer import tokenize, tokens_with_exact_identifier
from .types import Schema, ToolDocument


def tool_name(schema: object) -> str:
    if not isinstance(schema, dict):
        return ""
    function = schema.get("function") or {}
    return str(schema.get("name") or (function.get("name") if isinstance(function, dict) else "") or "")


def tool_description(schema: object) -> str:
    if not isinstance(schema, dict):
        return ""
    function = schema.get("function") or {}
    return str(schema.get("description") or (function.get("description") if isinstance(function, dict) else "") or "")


def tool_toolset(schema: object) -> str | None:
    if not isinstance(schema, dict):
        return None
    for key in ("toolset", "tool_set", "namespace", "server", "mcp_server"):
        value = schema.get(key)
        if value:
            return str(value)
    return None


def _schema_parameters(schema: object) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    params = schema.get("parameters") or schema.get("input_schema") or {}
    if not params and isinstance(schema.get("function"), dict):
        params = schema["function"].get("parameters") or {}
    return params if isinstance(params, dict) else {}


def _walk_schema(value: Any, seen: set[int] | None = None) -> Iterable[str]:
    if seen is None:
        seen = set()
    if isinstance(value, dict):
        marker = id(value)
        if marker in seen:
            return
        seen.add(marker)
        for key, nested in value.items():
            yield str(key)
            if key in {"description", "title", "enum"}:
                yield str(nested)
            yield from _walk_schema(nested, seen)
    elif isinstance(value, list):
        marker = id(value)
        if marker in seen:
            return
        seen.add(marker)
        for item in value[:25]:
            yield from _walk_schema(item, seen)
    elif isinstance(value, (str, int, float, bool)):
        yield str(value)


def build_document(schema: Schema) -> ToolDocument:
    name = tool_name(schema)
    toolset = tool_toolset(schema)
    params = _schema_parameters(schema)
    parameter_tokens = set(tokenize(" ".join(params.get("properties", {}).keys())))
    chunks = [name, toolset or "", tool_description(schema), " ".join(_walk_schema(params))]
    tokens: list[str] = []
    tokens.extend(tokens_with_exact_identifier(name) * 4)
    if toolset:
        tokens.extend(tokens_with_exact_identifier(toolset) * 2)
    tokens.extend(tokenize("\n".join(chunks)))
    tokens.extend(list(parameter_tokens) * 2)
    return ToolDocument(name=name, schema=schema, text="\n".join(chunks), tokens=tokens, toolset=toolset, parameter_tokens=parameter_tokens)


def build_corpus(schemas: Iterable[Schema]) -> list[ToolDocument]:
    return [build_document(schema) for schema in schemas if tool_name(schema)]
