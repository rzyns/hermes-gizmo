"""Canonical Hermes Gizmo Python package.

This package is the canonical import namespace for Hermes Gizmo.  The
legacy :mod:`hermes_tool_slimmer` package remains supported as a
compatibility surface while the hard-rename path is staged.
"""

from __future__ import annotations

from hermes_tool_slimmer import __version__, register

__all__ = ["register", "__version__"]
