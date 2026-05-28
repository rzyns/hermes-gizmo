# Hermes Gizmo Compatibility

**Hermes Gizmo** is a private fork of the `alias8818/hermes-tool-slimmer` repo, managed in a local checkout. This document covers installation, selector hook wiring, and isolated-profile constraints specific to the Hermes Gizmo fork.

## What This Document Covers

- Selector hook contract and hooking mechanism
- Isolated-profile install (no plugin enablement on the default profile)
- Non-authorizations (what we do NOT do in this fork)
- Verifying the selector callback wiring
- Clean workspace rules

## Selector Hook Contract

Hermes Gizmo uses the same selector hook surface as upstream Tool Slimmer. The `select_tool_schemas` callback is injected between `pre_llm_call` and provider request construction.

### Registration Surface

The plugin probes three Hermes registration methods in order:

1. `ctx.register_tool_schema_selector(callback)` — preferred
2. `ctx.register_schema_selector(callback)` — legacy alias
3. `ctx.register_hook("select_tool_schemas", callback)` — generic hook

If none succeed, the plugin runs diagnostics-only (dashboard visible, CLI works, but no active slimming).

### Callback Signature

```python
def callback(
    user_message: str,
    conversation_history: list,
    schemas: list[dict],
    model: str,
    platform: str,
    provider: str | None = None,
    session_id: str | None = None,
    **kwargs,
) -> list[dict] | None:
```

Return a `list[dict]` of schemas to send to the provider, or `None` to defer to the next hook / original catalog.

### Fail-Open Behavior

The selector callback is wrapped in try/except by the integration layer. If any exception happens during selection:
- `fail_open: true` (default): the full original schema catalog is preserved.
- `fail_open: false`: the exception propagates (useful for debugging).

### No Core Patching Here

The Hermes Gizmo fork does **not** apply the `docs/hermes-core-selector-hook.patch` at runtime. The patch is provided as an upstreamable artifact only. If the environment's Hermes core already exposes `select_tool_schemas`, the plugin works out-of-the-box. If not, it remains diagnostics-only.

## Isolated-Profile Install

Hermes supports per-profile plugin paths and configurations. The Gizmo fork must be installed in a way that does not leak into other profiles.

### Recommended Layout

```
~/.hermes/profiles/hermes-gizmo/          # profile-scoped Hermes home
  config.yaml                             # plugins.enabled includes tool-slimmer
  plugins/
    tool-slimmer/ -> ../../.../repo/      # symlink or copy

# Source repo (this checkout)
/home/openclaw/dev/hermes-stuff/plugins/hermes-gizmo
```

### Config for Isolated Profile

In `~/.hermes/profiles/hermes-gizmo/config.yaml` (or wherever `HERMES_HOME` points for the profile):

```yaml
plugins:
  enabled:
    - tool-slimmer

tool_slimmer:
  enabled: true
  mode: keyword        # or hybrid / semantic_hybrid
  top_k: 8
  always_include:
    - terminal
    - read_file
    - write_file
    - patch
    - search_files
  fail_open: true
  dry_run: true      # start dry-run until you verify behavior
```

### Avoid Global Plugin Enablement

Do **not** add `tool-slimmer` to the root profile's `plugins.enabled` list unless that is explicitly intended. The Gizmo fork may have experimental modes (`semantic_hybrid`, progressive tools) that should not affect production profiles.

### Activation Steps

1. Activate the target profile (e.g., by setting `HERMES_PROFILE=hermes-gizmo` before launching Hermes).
2. Ensure the plugin source is discoverable under that profile's plugin path.
3. Launch Hermes. The plugin registration happens during plugin loading.
4. Run `hermes tool-slimmer doctor` to confirm:
   - Config is valid.
   - Plugin is enabled.
   - Core selector hook is available (or note if it is missing).

## Non-Authorizations

The following actions are **not authorized** for the Gizmo fork without separate approval:

- Submitting an upstream PR to `alias8818/hermes-tool-slimmer`
- Publishing a public package to PyPI or any package registry
- Installing/enabling the plugin on the default Hermes profile
- Restarting the Hermes gateway in a shared environment
- Changing provider credentials or API keys
- Destructive mutation of existing Tool Slimmer or Hermes core installs
- Running the generic hidden-tool broker (`--hidden-tool` execution) unless separately approved

Violating any of these may corrupt shared environments or expose experimental changes to other profiles.

## Clean Workspace Rules

Every worker run that modifies this repo must:

1. Only touch files within the repo worktree.
2. Commit scoped changes with a meaningful commit message.
3. Leave the worktree clean (`nothing to commit, working tree clean`).
4. Not modify files outside the repo unless the task explicitly requires it.
5. Not delete upstream remote references or alter `.git/config` origin URLs.

### Verifying Clean Worktree

```bash
git status          # should show nothing to commit
git diff --cached   # should be empty if not in the middle of a commit
git log --oneline -3
```

## Troubleshooting

### "Selector hook is unavailable"

If `doctor` shows `core_selector_hook: warn`, your Hermes core does not advertise `select_tool_schemas`. Options:
- Accept diagnostics-only mode (dashboard/CLI still work).
- Apply `docs/hermes-core-selector-hook.patch` to your Hermes core source and restart.

### "Plugin not listed in plugins.enabled"

If `doctor` shows `plugin_enabled: warn`, check that the active Hermes profile's `config.yaml` includes `tool-slimmer` in `plugins.enabled`.

### "Config file not found"

If `doctor` shows `config: fail`, verify:
- The profile's `HERMES_CONFIG` env var or default `~/.hermes/profiles/<name>/config.yaml` exists.
- YAML is valid.

### Semantic Hybrid Degrades to Keyword

If you see `semantic_hybrid embedding failed; degrading to keyword` in logs:
- You have not configured an embedding provider.
- Set `semantic_provider: openai` and ensure `OPENAI_API_KEY` is exported, or use a local embedding endpoint via `semantic_openai_base_url`.
- Without a real provider, the `semantic_hybrid` mode is functionally random — stick with `keyword` or `hybrid`.

## Related Documents

- `docs/hermes-core-integration.md` — full upstream integration notes
- `docs/hermes-core-selector-hook.patch` — minimal core patch artifact
- `docs/gizmo-eval-report.md` — benchmark report comparing selector modes
- `docs/quickstart.md` — quickstart for the fork
- `README.md` — project overview

---
*This document is part of the Hermes Gizmo fork. It is not a public release artifact.*
