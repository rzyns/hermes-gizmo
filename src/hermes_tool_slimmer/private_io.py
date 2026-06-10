from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def ensure_private_dir(path: Path) -> None:
    """Create a directory and best-effort restrict it to the current user."""

    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def write_private_text(path: Path, text: str) -> None:
    """Write text and best-effort restrict the file to the current user."""

    ensure_private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def write_private_json(path: Path, payload: Any, **json_kwargs: Any) -> None:
    """Write JSON and best-effort restrict the file to the current user."""

    write_private_text(path, json.dumps(payload, **json_kwargs))


def append_private_line(path: Path, line: str) -> None:
    """Append a line and best-effort restrict the file to the current user."""

    ensure_private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(line)
    try:
        path.chmod(0o600)
    except OSError:
        pass
