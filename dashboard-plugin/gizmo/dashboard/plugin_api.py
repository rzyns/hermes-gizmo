from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_LEGACY_PLUGIN_API = Path(__file__).resolve().parents[2] / "tool-slimmer" / "dashboard" / "plugin_api.py"
_MODULE_NAME = "_hermes_gizmo_legacy_dashboard_plugin_api"

if _MODULE_NAME in sys.modules:
    _legacy_module = sys.modules[_MODULE_NAME]
else:
    _spec = importlib.util.spec_from_file_location(_MODULE_NAME, _LEGACY_PLUGIN_API)
    if _spec is None or _spec.loader is None:  # pragma: no cover - broken source layout guard
        raise ImportError(f"Cannot load legacy dashboard plugin API from {_LEGACY_PLUGIN_API}")
    _legacy_module = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = _legacy_module
    _spec.loader.exec_module(_legacy_module)

router = _legacy_module.router

__all__ = ["router"]
