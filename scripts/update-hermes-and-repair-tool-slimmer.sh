#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_BIN_EXPLICIT=0
UPDATE_BACKUP_ARGS=()
INSTALL_ARGS=()

default_hermes_bin() {
  local venv_bin="$HERMES_HOME/hermes-agent/venv/bin/hermes"
  if [[ -x "$venv_bin" ]]; then
    printf '%s\n' "$venv_bin"
    return
  fi
  command -v hermes || true
}

HERMES_BIN="${HERMES_BIN:-$(default_hermes_bin)}"

usage() {
  cat <<'USAGE'
Update Hermes, then reinstall/repair Hermes Tool Slimmer.

Usage:
  scripts/update-hermes-and-repair-tool-slimmer.sh [options]

Options:
  --no-backup       Pass --no-backup to `hermes update`.
  --backup          Pass --backup to `hermes update`.
  --no-restart      Repair Tool Slimmer without restarting Hermes services.
  --hermes-bin PATH Hermes executable to use. Defaults to ~/.hermes/hermes-agent/venv/bin/hermes when present.
  --hermes-home PATH
                   Hermes home directory. Defaults to ~/.hermes.
  -h, --help        Show this help.

This script uses `hermes update --yes` so Hermes' stash-restore prompt does not
wait for a keypress. It keeps Hermes' normal backup behavior unless you pass
--no-backup.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-backup)
      UPDATE_BACKUP_ARGS=(--no-backup)
      shift
      ;;
    --backup)
      UPDATE_BACKUP_ARGS=(--backup)
      shift
      ;;
    --no-restart)
      INSTALL_ARGS+=(--no-restart)
      shift
      ;;
    --hermes-bin)
      HERMES_BIN="${2:-}"
      HERMES_BIN_EXPLICIT=1
      shift 2
      ;;
    --hermes-home)
      HERMES_HOME="${2:-}"
      INSTALL_ARGS+=(--hermes-home "$HERMES_HOME")
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

if [[ "$HERMES_BIN_EXPLICIT" != "1" ]]; then
  HERMES_BIN="$(default_hermes_bin)"
fi

step() {
  printf '\n==> %s\n' "$1"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

compatibility_notice() {
  cat <<'NOTICE'

==> Compatibility note
Recent Hermes Agent builds include native Tool Search for very large MCP/plugin
tool catalogs. That native Hermes feature is probably the better default when it
activates. Tool Slimmer detects Hermes' native bridge and will not double-slim
those requests. The update repair below preserves Tool Slimmer's dashboard,
counters, diagnostics, profiles, and deterministic slimming for requests where
native Tool Search is inactive.
NOTICE
}

[[ -n "$HERMES_BIN" ]] || fail "Hermes executable not found. Install Hermes or pass --hermes-bin PATH."
[[ -x "$HERMES_BIN" ]] || fail "Hermes executable is not executable: $HERMES_BIN"

HERMES_BIN="$(readlink -f "$HERMES_BIN")"
export HERMES_HOME

step "Updating Hermes non-interactively"
echo "Hermes: $HERMES_BIN"
echo "Hermes home: $HERMES_HOME"
compatibility_notice
"$HERMES_BIN" update --yes "${UPDATE_BACKUP_ARGS[@]}"

step "Repairing Tool Slimmer after Hermes update"
bash "$ROOT_DIR/scripts/install-hermes-tool-slimmer.sh" \
  --hermes-bin "$HERMES_BIN" \
  --hermes-home "$HERMES_HOME" \
  "${INSTALL_ARGS[@]}"

step "Done"
echo "Hermes was updated and Tool Slimmer was repaired. Check above for the doctor result."
