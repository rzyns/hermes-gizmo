# Contributing to Hermes Gizmo

Thanks for helping improve Hermes Gizmo. This project is intentionally small, deterministic, and fail-open because it influences which tool schemas Hermes sends to model providers.

Hermes Gizmo is based on upstream [`alias8818/hermes-tool-slimmer`](https://github.com/alias8818/hermes-tool-slimmer) and remains MIT licensed. Please preserve upstream attribution and legacy `tool-slimmer` compatibility unless a change explicitly includes a reviewed migration plan.

## Development setup

```bash
git clone https://github.com/rzyns/hermes-gizmo.git
cd hermes-gizmo
python -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

## Validation before a PR

Run the same checks used for release:

```bash
ruff check .
mypy src tests
python -m compileall -q src tests dashboard-plugin/tool-slimmer dashboard-plugin/gizmo
pytest -q
python -m build
scripts/check-wheel-assets.sh
```

If you update `docs/hermes-core-selector-hook.patch`, also validate it against a clean Hermes checkout:

```bash
git clone https://github.com/NousResearch/hermes-agent.git /tmp/hermes-agent-core
cd /tmp/hermes-agent-core
git apply --check /path/to/hermes-gizmo/docs/hermes-core-selector-hook.patch
git apply /path/to/hermes-gizmo/docs/hermes-core-selector-hook.patch
python -m py_compile run_agent.py hermes_cli/plugins.py tests/hermes_cli/test_tool_schema_selector_hook.py
PYTHONPATH=$PWD pytest -q -o addopts='' tests/hermes_cli/test_tool_schema_selector_hook.py
git diff --check
```

## Design rules

- Do not monkeypatch Hermes provider internals for the release path.
- Keep selector behavior deterministic unless an optional mode clearly documents otherwise.
- Preserve fail-open behavior: selector errors must not remove user tools.
- Do not resurrect tools that Hermes already disabled.
- Preserve diagnostics privacy: no raw prompts, secrets, or session IDs in public support output.
- Add regression tests for ranking, provider gating, config behavior, packaging, and compatibility changes.
