from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import hermes_home
from .corpus import build_corpus, tool_description, tool_name, tool_toolset
from .corpus import _schema_parameters
from .types import Schema


@dataclass
class IndexStore:
    root: Path
    path: Path

    def __init__(self, root: Path | str | None = None) -> None:
        root = Path(root or hermes_home() / "tool-slimmer").expanduser()
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.path = root / "tool_index.json"
        self.live_schemas_path = root / "live_tool_schemas.json"

    @staticmethod
    def checksum(schemas: list[Schema]) -> str:
        normalized = [
            {"name": tool_name(schema), "toolset": tool_toolset(schema), "description": tool_description(schema), "parameters": _schema_parameters(schema)}
            for schema in schemas
        ]
        normalized.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str, separators=(",", ":")))
        payload = json.dumps(normalized, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return None

    def save_live_schemas(self, schemas: list[Schema], context: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "checksum": self.checksum(schemas),
            "total_tools": len(build_corpus(schemas)),
            "schemas": schemas,
            "context": context or {},
        }
        self.live_schemas_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return payload

    def load_live_schemas(self, min_total_tools: int = 0, require_session: bool = True) -> list[Schema]:
        if not self.live_schemas_path.exists():
            return []
        try:
            payload = json.loads(self.live_schemas_path.read_text())
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict):
            return []
        if _safe_int(payload.get("total_tools")) < min_total_tools:
            return []
        context = payload.get("context")
        if require_session and (not isinstance(context, dict) or not context.get("session_id")):
            return []
        schemas = payload.get("schemas")
        if not isinstance(schemas, list):
            return []
        checksum = payload.get("checksum")
        if isinstance(checksum, str) and checksum != self.checksum(schemas):
            return []
        return schemas

    def rebuild(self, schemas: list[Schema]) -> dict[str, Any]:
        docs = build_corpus(schemas)
        payload = {
            "checksum": self.checksum(schemas),
            "total_tools": len(docs),
            "documents": [{"name": doc.name, "toolset": doc.toolset, "tokens": doc.tokens, "text": doc.text} for doc in docs],
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        return payload

    def ensure(self, schemas: list[Schema]) -> dict[str, Any]:
        current = self.load()
        checksum = self.checksum(schemas)
        if not current or current.get("checksum") != checksum:
            return self.rebuild(schemas)
        return current


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
