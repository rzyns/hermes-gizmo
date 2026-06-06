#!/usr/bin/env bash
set -euo pipefail
# check-wheel-assets.sh — reproducible regression guard for wheel/sdist packaging
# Usage: bash scripts/check-wheel-assets.sh
# Returns 0 when wheel and sdist both include required plugin/dashboard assets.

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
SDIST_LIST_FILE="$TMPDIR/sdist-list.txt"
tar tzf "$SDIST" > "$SDIST_LIST_FILE"
SDIST_PREFIX=$(head -n1 "$SDIST_LIST_FILE" | cut -d'/' -f1)

MISSING=0

check_wheel_member() {
  local member="$1"
  if unzip -l "$WHEEL" | grep -q "$member"; then
    echo "OK  wheel contains $member"
  else
    echo "FAIL wheel missing $member"
    MISSING=1
  fi
}

check_sdist_member() {
  local member="$1"
  if grep -q "${SDIST_PREFIX}/${member}" "$SDIST_LIST_FILE"; then
    echo "OK  sdist contains $member"
  else
    echo "FAIL sdist missing $member"
    MISSING=1
  fi
}

required_members=(
  "NOTICE"
  "plugin.yaml"
  "dashboard/dist/index.js"
  "dashboard/dist/style.css"
  "dashboard/manifest.json"
  "dashboard/plugin_api.py"
  "dashboard-plugin/tool-slimmer/__init__.py"
  "dashboard-plugin/tool-slimmer/plugin.yaml"
  "dashboard-plugin/tool-slimmer/dashboard/manifest.json"
  "dashboard-plugin/gizmo/__init__.py"
  "dashboard-plugin/gizmo/plugin.yaml"
  "dashboard-plugin/gizmo/dashboard/manifest.json"
)

echo "=== Wheel membership ==="
for member in "${required_members[@]}"; do
  check_wheel_member "$member"
done

echo "=== Sdist membership ==="
for member in "${required_members[@]}"; do
  check_sdist_member "$member"
done

if [[ "$MISSING" -eq 0 ]]; then
  echo "PASS wheel and sdist include required plugin/dashboard assets"
  exit 0
else
  echo "FAIL some packaging checks failed"
  exit 1
fi
