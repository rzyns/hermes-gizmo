"""Compatibility alias for :mod:`hermes_tool_slimmer.anthropic_tool_search`."""

from __future__ import annotations

from importlib import import_module as _import_module
import sys as _sys

_legacy_module = _import_module("hermes_tool_slimmer.anthropic_tool_search")
_sys.modules[__name__] = _legacy_module
