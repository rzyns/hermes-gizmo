#!/usr/bin/env bash
set -euo pipefail
# check-wheel-assets.sh — reproducible regression guard for wheel/sdist packaging
# Usage: bash scripts/check-wheel-assets.sh
# Returns 0 when wheel and sdist both include required dashboard assets.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Build wheel + sdist in a clean temporary directory
if command -v uvx >/dev/null 2>&1; then
  uvx --from hatchling hatchling build -d "$TMPDIR" >/dev/null
else
  python -m hatchling build -d "$TMPDIR" >/dev/null
fi

WHEEL=$(find "$TMPDIR" -maxdepth 1 -name '*.whl' | head -n1)
SDIST=$(find "$TMPDIR" -maxdepth 1 -name '*.tar.gz' | head -n1)

MISSING=0

check_member() {
  local archive="$1"
  local member="$2"
  local label="$3"
  if unzip -l "$archive" | grep -q "$member"; then
    echo "OK  $label contains $member"
  else
    echo "FAIL $label missing $member"
    MISSING=1
  fi
}

echo "=== Wheel membership ==="
check_member "$WHEEL" "dashboard/dist/index.js"   "wheel"
check_member "$WHEEL" "dashboard/dist/style.css"  "wheel"
check_member "$WHEEL" "dashboard/manifest.json"   "wheel"
check_member "$WHEEL" "dashboard/plugin_api.py"   "wheel"
check_member "$WHEEL" "dashboard-plugin/tool-slimmer/__init__.py" "wheel"
check_member "$WHEEL" "dashboard-plugin/tool-slimmer/plugin.yaml" "wheel"

echo "=== Sdist membership ==="
SDIST_LIST_FILE="$TMPDIR/sdist-list.txt"
tar tzf "$SDIST" > "$SDIST_LIST_FILE"
SDIST_PREFIX=$(head -n1 "$SDIST_LIST_FILE" | cut -d'/' -f1)
if grep -q "${SDIST_PREFIX}/dashboard/dist/index.js" "$SDIST_LIST_FILE"; then
  echo "OK  sdist contains dashboard/dist/index.js"
else
  echo "FAIL sdist missing dashboard/dist/index.js"
  MISSING=1
fi
if grep -q "${SDIST_PREFIX}/dashboard/dist/style.css" "$SDIST_LIST_FILE"; then
  echo "OK  sdist contains dashboard/dist/style.css"
else
  echo "FAIL sdist missing dashboard/dist/style.css"
  MISSING=1
fi

if [[ "$MISSING" -eq 0 ]]; then
  echo "PASS wheel and sdist include required dashboard assets"
  exit 0
else
  echo "FAIL some packaging checks failed"
  exit 1
fi
