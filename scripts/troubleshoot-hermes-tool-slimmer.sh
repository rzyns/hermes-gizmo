#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_BIN="${HERMES_BIN:-$(command -v hermes || true)}"
QUICK=0

usage() {
  cat <<'USAGE'
Print a deterministic Tool Slimmer health report.

Usage:
  scripts/troubleshoot-hermes-tool-slimmer.sh [options]

Options:
  --quick            Shorter report for installer output.
  --hermes-bin PATH  Hermes executable to use. Defaults to `command -v hermes`.
  --hermes-home PATH Hermes home directory. Defaults to ~/.hermes.
  -h, --help         Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick)
      QUICK=1
      shift
      ;;
    --hermes-bin)
      HERMES_BIN="${2:-}"
      shift 2
      ;;
    --hermes-home)
      HERMES_HOME="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

section() {
  printf '\n== %s ==\n' "$1"
}

run_or_warn() {
  local label="$1"
  shift
  echo "+ $label"
  if ! "$@"; then
    echo "WARN: command failed: $label" >&2
  fi
}

[[ -n "$HERMES_BIN" ]] || {
  echo "ERROR: hermes executable not found. Pass --hermes-bin PATH." >&2
  exit 1
}

HERMES_BIN="$(readlink -f "$HERMES_BIN")"
HERMES_VENV_DIR="$(dirname "$HERMES_BIN")"
HERMES_PYTHON="${HERMES_PYTHON:-$HERMES_VENV_DIR/python}"
[[ -x "$HERMES_PYTHON" ]] || HERMES_PYTHON="${HERMES_VENV_DIR}/python3"
[[ -x "$HERMES_PYTHON" ]] || {
  echo "ERROR: could not find Hermes Python next to $HERMES_BIN" >&2
  exit 1
}

export HERMES_HOME

section "Paths"
echo "Hermes: $HERMES_BIN"
echo "Python: $HERMES_PYTHON"
echo "Hermes home: $HERMES_HOME"
echo "User plugin dir: $HERMES_HOME/plugins/tool-slimmer"
echo "Decision log: $HERMES_HOME/tool-slimmer/decisions.jsonl"

section "Python Package"
"$HERMES_PYTHON" - <<'PY'
from __future__ import annotations

import importlib.metadata as md
import importlib.util

spec = importlib.util.find_spec("hermes_tool_slimmer")
print(f"importable: {bool(spec)}")
print(f"module: {spec.origin if spec else 'missing'}")
try:
    print(f"version: {md.version('hermes-tool-slimmer')}")
except md.PackageNotFoundError:
    print("version: missing")
eps = [ep for ep in md.entry_points(group="hermes_agent.plugins") if ep.name == "tool-slimmer"]
print(f"entry_point: {bool(eps)}")
PY

section "Privacy"
run_or_warn "hermes tool-slimmer privacy" "$HERMES_BIN" tool-slimmer privacy

section "Hermes Doctor"
run_or_warn "hermes tool-slimmer doctor" "$HERMES_BIN" tool-slimmer doctor

section "Hermes Plugin List"
echo "+ hermes plugins list"
"$HERMES_BIN" plugins list | grep -E 'tool-slimmer|Name|Status|enabled' || true

section "Installed Files"
if [[ -d "$HERMES_HOME/plugins/tool-slimmer" ]]; then
  find "$HERMES_HOME/plugins/tool-slimmer" -maxdepth 3 -type f | sort
else
  echo "missing: $HERMES_HOME/plugins/tool-slimmer"
fi

section "Dashboard"
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user is-active hermes-dashboard.service 2>/dev/null || true
fi

if command -v curl >/dev/null 2>&1; then
  if curl -fsS http://127.0.0.1:9119/api/dashboard/plugins >/tmp/tool-slimmer-plugins.json 2>/dev/null; then
    "$HERMES_PYTHON" - <<'PY'
import json
from pathlib import Path

plugins = json.loads(Path("/tmp/tool-slimmer-plugins.json").read_text())
match = [p for p in plugins if p.get("name") == "tool-slimmer"]
print(f"manifest_visible: {bool(match)}")
if match:
    p = match[0]
    print(f"label: {p.get('label')}")
    print(f"has_api: {p.get('has_api')}")
    print(f"entry: {p.get('entry')}")
    print(f"css: {p.get('css')}")
PY
  else
    echo "dashboard_plugins_endpoint: unavailable"
  fi
else
  echo "curl: missing"
fi

if [[ "$QUICK" == "0" ]]; then
  section "Recent Real Events"
  "$HERMES_PYTHON" - <<'PY'
from hermes_tool_slimmer.metrics import summarize_decisions

summary = summarize_decisions(require_session=True)
totals = summary.get("totals", {})
print(f"real_events: {totals.get('events', 0)}")
print(f"skipped_events: {totals.get('skipped_events', 0)}")
print(f"approx_tokens_saved: {totals.get('approx_tokens_saved', 0)}")
print(f"last_event_at: {summary.get('last_event_at')}")
PY

  section "Recent Decisions"
  if [[ -f "$HERMES_HOME/tool-slimmer/decisions.jsonl" ]]; then
    tail -5 "$HERMES_HOME/tool-slimmer/decisions.jsonl"
  else
    echo "No decisions logged yet. Run a Hermes turn after install."
  fi
fi

section "Plain-English Result"
"$HERMES_PYTHON" - "$HERMES_BIN" <<'PY'
from __future__ import annotations

import json
import subprocess
import sys

try:
    raw = subprocess.check_output([sys.argv[1], "tool-slimmer", "doctor"], text=True)
    data = json.loads(raw)
except Exception as exc:
    print(f"Needs attention: doctor failed ({exc}).")
    raise SystemExit(0)

checks = data.get("checks", {})
failed = [name for name, check in checks.items() if check.get("status") == "fail"]
warned = [name for name, check in checks.items() if check.get("status") == "warn"]
if failed:
    print("Needs attention: failing checks: " + ", ".join(failed))
elif warned:
    print("Usable with warnings: " + ", ".join(warned))
else:
    print("Ready: Tool Slimmer is installed, enabled, and active.")
PY
