"""Canonical Hermes Gizmo CLI wrapper.

The implementation lives in :mod:`hermes_tool_slimmer.cli` so legacy
``hermes-tool-slimmer`` and ``hermes tool-slimmer`` commands keep working.
This wrapper only gives the canonical console script a canonical program name.
"""

from __future__ import annotations

import argparse
import sys

from hermes_tool_slimmer.cli import handle_cli, setup_argparse


def main(argv: list[str] | None = None) -> int:
    """Run the canonical ``hermes-gizmo`` console command."""
    parser = argparse.ArgumentParser(prog="hermes-gizmo")
    setup_argparse(parser)
    return handle_cli(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
