#!/usr/bin/env bash
set -euo pipefail
# check-dashboard-assets.sh — regression guard for dashboard asset layout
# Usage: bash scripts/check-dashboard-assets.sh
# Returns 0 when the canonical layout is intact, non-zero otherwise.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MISSING=0

for asset in dashboard/dist/index.js dashboard/dist/style.css; do
  if [[ -f "$ROOT_DIR/$asset" ]]; then
    echo "OK  $asset ($(wc -c < "$ROOT_DIR/$asset") bytes)"
  else
    echo "MISSING $asset"
    MISSING=1
  fi
done

# Verify the installer references the canonical source
expected_dashboard_src="DASHBOARD_SRC=\"\$ROOT_DIR/dashboard\""
if grep -Fq "$expected_dashboard_src" "$ROOT_DIR/scripts/install-hermes-tool-slimmer.sh"; then
  echo "OK  installer references canonical dashboard/dist"
else
  echo "FAIL installer does not reference canonical dashboard/dist"
  MISSING=1
fi

# Verify pyproject.toml artifacts list references canonical path
if grep -q '"/dashboard/dist/index.js"' "$ROOT_DIR/pyproject.toml"; then
  echo "OK  pyproject.toml artifacts list canonical"
else
  echo "FAIL pyproject.toml artifacts list not canonical"
  MISSING=1
fi

if [[ "$MISSING" -eq 0 ]]; then
  echo "PASS all checks"
  exit 0
else
  echo "FAIL some checks failed"
  exit 1
fi
