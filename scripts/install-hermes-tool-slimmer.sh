#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_NAME="tool-slimmer"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PATCH_CORE=1
RESTART_SERVICES=1

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
Install or repair Hermes Tool Slimmer for the local Hermes dashboard.

Usage:
  scripts/install-hermes-tool-slimmer.sh [options]

Options:
  --no-core-patch     Do not patch Hermes core if select_tool_schemas is missing.
  --no-restart        Do not restart hermes-dashboard/hermes-gateway systemd user services.
  --hermes-bin PATH   Hermes executable to use. Defaults to ~/.hermes/hermes-agent/venv/bin/hermes when present, then `command -v hermes`.
  --hermes-home PATH  Hermes home directory. Defaults to ~/.hermes.
  -h, --help          Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-core-patch)
      PATCH_CORE=0
      shift
      ;;
    --no-restart)
      RESTART_SERVICES=0
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

step() {
  printf '\n==> %s\n' "$1"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ -n "$HERMES_BIN" ]] || fail "Hermes executable not found. Install Hermes or pass --hermes-bin PATH."
[[ -x "$HERMES_BIN" ]] || fail "Hermes executable is not executable: $HERMES_BIN"

HERMES_BIN="$(readlink -f "$HERMES_BIN")"
HERMES_VENV_DIR="$(dirname "$HERMES_BIN")"
HERMES_PYTHON="${HERMES_PYTHON:-$HERMES_VENV_DIR/python}"
[[ -x "$HERMES_PYTHON" ]] || HERMES_PYTHON="${HERMES_VENV_DIR}/python3"
[[ -x "$HERMES_PYTHON" ]] || fail "Could not find Hermes Python next to $HERMES_BIN"

export HERMES_HOME

step "Using Hermes"
echo "Hermes: $HERMES_BIN"
echo "Python: $HERMES_PYTHON"
echo "Hermes home: $HERMES_HOME"

step "Installing Python package into Hermes environment"
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$HERMES_PYTHON" -e "$ROOT_DIR"
elif "$HERMES_PYTHON" -m pip --version >/dev/null 2>&1; then
  "$HERMES_PYTHON" -m pip install -e "$ROOT_DIR"
else
  fail "Neither uv nor pip is available. Install uv or add pip to the Hermes Python environment."
fi

step "Installing dashboard/user plugin files"
TARGET_DIR="$HERMES_HOME/plugins/$PLUGIN_NAME"
TMP_DIR="$HERMES_HOME/plugins/.${PLUGIN_NAME}.tmp.$$"
PLUGIN_SRC="$ROOT_DIR/dashboard-plugin/$PLUGIN_NAME"
DASHBOARD_SRC="$ROOT_DIR/dashboard"
mkdir -p "$HERMES_HOME/plugins"
if [[ "$(readlink -f "$ROOT_DIR")" == "$(readlink -f "$TARGET_DIR" 2>/dev/null || printf '%s' "$TARGET_DIR")" ]]; then
  cp -R "$PLUGIN_SRC"/. "$TARGET_DIR"/
else
  rm -rf "$TMP_DIR"
  cp -R "$PLUGIN_SRC" "$TMP_DIR"
  rm -rf "$TARGET_DIR"
  mv "$TMP_DIR" "$TARGET_DIR"
fi
# Ensure built dashboard assets are present at the served layout
mkdir -p "$TARGET_DIR/dashboard/dist"
cp "$DASHBOARD_SRC/dist/index.js" "$DASHBOARD_SRC/dist/style.css" "$TARGET_DIR/dashboard/dist/"
echo "Installed: $TARGET_DIR"

step "Enabling Hermes plugin"
"$HERMES_BIN" plugins enable "$PLUGIN_NAME"

core_hook_status() {
  "$HERMES_BIN" tool-slimmer doctor 2>/dev/null | "$HERMES_PYTHON" -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print("unknown")
    raise SystemExit(0)
print(data.get("checks", {}).get("core_selector_hook", {}).get("status", "unknown"))
'
}

patch_core() {
  "$HERMES_PYTHON" - <<'PY'
from __future__ import annotations

import importlib.util
from pathlib import Path

plugins_spec = importlib.util.find_spec("hermes_cli.plugins")
conversation_spec = importlib.util.find_spec("agent.conversation_loop")
helpers_spec = importlib.util.find_spec("agent.chat_completion_helpers")
run_agent_spec = importlib.util.find_spec("run_agent")
if plugins_spec is None or plugins_spec.origin is None:
    raise SystemExit("Could not locate hermes_cli.plugins in Hermes Python")

plugins_py = Path(plugins_spec.origin)

if not plugins_py.exists():
    raise SystemExit("Could not find hermes_cli.plugins source file")

plugins_text = plugins_py.read_text(encoding="utf-8")
if '"select_tool_schemas"' not in plugins_text:
    marker = '    "pre_llm_call",\n'
    if marker not in plugins_text:
        raise SystemExit("Could not patch VALID_HOOKS in hermes_cli/plugins.py")
    plugins_text = plugins_text.replace(marker, marker + '    "select_tool_schemas",\n', 1)

    doc_marker = (
        '            {"context": "recalled text..."}\n'
        '            "recalled text..."          # plain string, equivalent\n\n'
    )
    doc_insert = (
        doc_marker +
        "        For ``select_tool_schemas``, callbacks receive a request-local copy\n"
        "        of the full enabled schema list and may return a replacement list.\n"
        "        Callers should apply only the first non-None list so multiple schema\n"
        "        selectors do not compose implicitly. Exceptions are swallowed here so\n"
        "        selection fails open to the original request-local schema list.\n\n"
    )
    if doc_marker in plugins_text:
        plugins_text = plugins_text.replace(doc_marker, doc_insert, 1)
plugins_py.write_text(plugins_text, encoding="utf-8")

patched_files = [plugins_py]
patch_notes = []


def patch_modular_core(conversation_py: Path, helpers_py: Path) -> None:
    if not conversation_py.exists() or not helpers_py.exists():
        raise SystemExit("Could not find modular Hermes core source files")

    helpers_text = helpers_py.read_text(encoding="utf-8")
    legacy_helper_probe = (
        '    tools_for_api = getattr(agent, "_tools_for_request", None)\n'
        "    if tools_for_api is None:\n"
        "        tools_for_api = agent.tools\n"
    )
    if legacy_helper_probe in helpers_text:
        helpers_text = helpers_text.replace(legacy_helper_probe, "    tools_for_api = agent.tools\n", 1)
        patch_notes.append("modular-helper-request-tools")
    else:
        patch_notes.append("modular-helper-direct-tools")
    helpers_py.write_text(helpers_text, encoding="utf-8")

    conversation_text = conversation_py.read_text(encoding="utf-8")
    if 'def _select_tools_for_request() -> list | None:' not in conversation_text:
        marker = '        # Main conversation loop\n'
        marker_label = "modular-main-loop-comment"
        if marker not in conversation_text:
            marker = '        while retry_count < max_retries:\n'
            marker_label = "modular-retry-loop"
        selector = (
            "        def _select_tools_for_request() -> list | None:\n"
            "            if not agent.tools:\n"
            "                return agent.tools\n"
            "            tools_for_request = list(agent.tools)\n"
            "            try:\n"
            "                from hermes_cli.plugins import invoke_hook as _invoke_hook\n"
            "                _schema_results = _invoke_hook(\n"
            '                    "select_tool_schemas",\n'
            "                    session_id=agent.session_id,\n"
            "                    user_message=original_user_message,\n"
            "                    conversation_history=list(messages),\n"
            "                    schemas=tools_for_request,\n"
            "                    model=agent.model,\n"
            '                    platform=getattr(agent, "platform", None) or "",\n'
            "                    provider=(\n"
            '                        getattr(agent, "provider", None)\n'
            '                        or getattr(agent, "model_provider", None)\n'
            "                    ),\n"
            "                )\n"
            "                _schema_lists = [result for result in _schema_results if isinstance(result, list)]\n"
            "                if _schema_lists:\n"
            "                    if len(_schema_lists) > 1:\n"
            "                        logger.warning(\n"
            '                            "Multiple select_tool_schemas hooks returned schemas; using the first result"\n'
            "                        )\n"
            "                    return _schema_lists[0]\n"
            "            except Exception as exc:\n"
            '                logger.warning("select_tool_schemas hook failed; using original tools: %s", exc)\n'
            "            return tools_for_request\n\n"
        )
        if marker not in conversation_text:
            raise SystemExit("Could not find request retry loop marker in agent/conversation_loop.py")
        conversation_text = conversation_text.replace(marker, selector + marker, 1)
        patch_notes.append(marker_label)
    else:
        patch_notes.append("modular-selector-present")

    old_request_patch = (
        "                tools_for_request = _select_tools_for_request()\n"
        "                agent._tools_for_request = tools_for_request\n"
        "                try:\n"
        "                    api_kwargs = agent._build_api_kwargs(api_messages)\n"
        "                finally:\n"
        "                    agent._tools_for_request = None\n"
    )
    new_request_patch = (
        "                tools_for_request = _select_tools_for_request()\n"
        "                original_tools = agent.tools\n"
        "                agent.tools = tools_for_request\n"
        "                try:\n"
        "                    api_kwargs = agent._build_api_kwargs(api_messages)\n"
        "                finally:\n"
        "                    agent.tools = original_tools\n"
    )
    if old_request_patch in conversation_text:
        conversation_text = conversation_text.replace(old_request_patch, new_request_patch, 1)
        patch_notes.append("modular-request-legacy-tools-for-request")
    elif "original_tools = agent.tools" not in conversation_text:
        old = "                api_kwargs = agent._build_api_kwargs(api_messages)\n"
        if old not in conversation_text:
            raise SystemExit("Could not patch request-local API kwargs construction")
        conversation_text = conversation_text.replace(old, new_request_patch, 1)
        patch_notes.append("modular-request-build-api-kwargs")
    else:
        patch_notes.append("modular-request-present")

    if "tool_count=len(agent.tools or [])" in conversation_text:
        conversation_text = conversation_text.replace(
            "tool_count=len(agent.tools or []),",
            "tool_count=len(tools_for_request if tools_for_request is not None else (agent.tools or [])),",
            1,
        )

    conversation_py.write_text(conversation_text, encoding="utf-8")
    patched_files.extend([conversation_py, helpers_py])


def patch_monolithic_core(run_agent_py: Path) -> None:
    if not run_agent_py.exists():
        raise SystemExit("Could not find monolithic run_agent.py source file")

    run_text = run_agent_py.read_text(encoding="utf-8")
    active_tools_probe = (
        "    def _active_tools_for_request(self):\n"
        '        request_tools = getattr(self, "_tools_for_request", None)\n'
        "        return request_tools if request_tools is not None else self.tools\n\n"
    )
    if active_tools_probe in run_text:
        run_text = run_text.replace(active_tools_probe, "", 1)
        patch_notes.append("monolithic-active-tools-helper")
    if "        tools_for_api = self._active_tools_for_request()\n" in run_text:
        run_text = run_text.replace(
            "        tools_for_api = self._active_tools_for_request()\n",
            "        tools_for_api = self.tools\n",
            1,
        )
        patch_notes.append("monolithic-tools-for-api")

    if 'def _select_tools_for_request() -> list | None:' not in run_text:
        marker = '        # Main conversation loop\n'
        selector = (
            "        def _select_tools_for_request() -> list | None:\n"
            "            if not self.tools:\n"
            "                return self.tools\n"
            "            tools_for_request = list(self.tools)\n"
            "            try:\n"
            "                from hermes_cli.plugins import invoke_hook as _invoke_hook\n"
            "                _schema_results = _invoke_hook(\n"
            '                    "select_tool_schemas",\n'
            "                    session_id=self.session_id,\n"
            "                    user_message=original_user_message,\n"
            "                    conversation_history=list(messages),\n"
            "                    schemas=tools_for_request,\n"
            "                    model=self.model,\n"
            '                    platform=getattr(self, "platform", None) or "",\n'
            "                    provider=(\n"
            '                        getattr(self, "provider", None)\n'
            '                        or getattr(self, "model_provider", None)\n'
            "                    ),\n"
            "                )\n"
            "                _schema_lists = [r for r in _schema_results if isinstance(r, list)]\n"
            "                if _schema_lists:\n"
            "                    if len(_schema_lists) > 1:\n"
            "                        logger.warning(\n"
            '                            "Multiple select_tool_schemas hooks returned schemas; "\n'
            '                            "using the first result"\n'
            "                        )\n"
            "                    return _schema_lists[0]\n"
            "            except Exception as exc:\n"
            '                logger.warning("select_tool_schemas hook failed; using original tools: %s", exc)\n'
            "            return tools_for_request\n\n"
        )
        if marker not in run_text:
            raise SystemExit("Could not find main conversation loop marker in run_agent.py")
        run_text = run_text.replace(marker, selector + marker, 1)
        patch_notes.append("monolithic-main-loop-comment")
    else:
        patch_notes.append("monolithic-selector-present")

    old_request_patch = (
        "                    tools_for_request = _select_tools_for_request()\n"
        "                    self._tools_for_request = tools_for_request\n"
        "                    try:\n"
        "                        api_kwargs = self._build_api_kwargs(api_messages)\n"
        "                    finally:\n"
        "                        self._tools_for_request = None\n"
    )
    new_request_patch = (
        "                    tools_for_request = _select_tools_for_request()\n"
        "                    original_tools = self.tools\n"
        "                    self.tools = tools_for_request\n"
        "                    try:\n"
        "                        api_kwargs = self._build_api_kwargs(api_messages)\n"
        "                    finally:\n"
        "                        self.tools = original_tools\n"
    )
    if old_request_patch in run_text:
        run_text = run_text.replace(old_request_patch, new_request_patch, 1)
        patch_notes.append("monolithic-request-legacy-tools-for-request")
    elif "original_tools = self.tools" not in run_text:
        old = "                    api_kwargs = self._build_api_kwargs(api_messages)\n"
        if old not in run_text:
            raise SystemExit("Could not patch request-local API kwargs construction")
        run_text = run_text.replace(old, new_request_patch, 1)
        patch_notes.append("monolithic-request-build-api-kwargs")
    else:
        patch_notes.append("monolithic-request-present")

    if "tool_count=len(self.tools or [])" in run_text:
        run_text = run_text.replace(
            "tool_count=len(self.tools or []),",
            "tool_count=len(tools_for_request if tools_for_request is not None else (self.tools or [])),",
            1,
        )

    run_agent_py.write_text(run_text, encoding="utf-8")
    patched_files.append(run_agent_py)


if conversation_spec is not None and conversation_spec.origin and helpers_spec is not None and helpers_spec.origin:
    patch_modular_core(Path(conversation_spec.origin), Path(helpers_spec.origin))
elif run_agent_spec is not None and run_agent_spec.origin:
    patch_monolithic_core(Path(run_agent_spec.origin))
else:
    raise SystemExit("Could not locate a supported Hermes core layout to patch")

print("Patched Hermes core: " + ", ".join(str(path) for path in patched_files))
if patch_notes:
    print("Patch strategy: " + ", ".join(patch_notes))
PY
}

step "Checking Hermes core selector hook"
HOOK_STATUS="$(core_hook_status || true)"
if [[ "$HOOK_STATUS" == "pass" ]]; then
  echo "Core selector hook is available."
  if [[ "$PATCH_CORE" == "1" ]]; then
    echo "Verifying request-local schema selector integration."
    patch_core
  fi
elif [[ "$PATCH_CORE" == "1" ]]; then
  echo "Core selector hook is missing; patching Hermes core."
  patch_core
else
  echo "Core selector hook is missing. Dashboard will work, but active schema slimming needs the hook."
fi

if [[ "$PATCH_CORE" == "1" ]]; then
  "$HERMES_PYTHON" - <<'PY'
import importlib.util
import py_compile

for name in ("hermes_cli.plugins", "agent.conversation_loop", "agent.chat_completion_helpers", "run_agent"):
    spec = importlib.util.find_spec(name)
    if spec and spec.origin:
        py_compile.compile(spec.origin, doraise=True)
PY
fi

step "Restarting Hermes services"
if [[ "$RESTART_SERVICES" == "1" ]] && command -v systemctl >/dev/null 2>&1; then
  if systemctl --user list-unit-files --type=service --no-pager | grep -q '^hermes-dashboard.service'; then
    systemctl --user restart hermes-dashboard.service || true
  fi
  if systemctl --user list-unit-files --type=service --no-pager | grep -q '^hermes-gateway.service'; then
    systemctl --user restart hermes-gateway.service || true
  fi
else
  echo "Skipping service restart."
fi

step "Final health report"
if bash "$ROOT_DIR/scripts/troubleshoot-hermes-tool-slimmer.sh" --hermes-bin "$HERMES_BIN" --hermes-home "$HERMES_HOME"; then
  echo "Install completed."
else
  echo "Install completed with health warnings; see report above."
fi
exit 0
