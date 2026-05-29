# Quickstart — Hermes Gizmo Fork

This is the quickstart for the **Hermes Gizmo fork** of Tool Slimmer. For upstream install (dashboard, script installer), see the original quickstart and README.

## Prerequisites

- Python 3.11+
- A local checkout of this repo
- A dedicated Hermes profile (e.g., `hermes-gizmo`) — do not install on the default profile

## 1. Install (Isolated Profile)

Set the profile and home directory:

```bash
export HERMES_PROFILE=hermes-gizmo
export HERMES_HOME="$HOME/.hermes/profiles/$HERMES_PROFILE"
```

Install the package from this local checkout:

```bash
cd /home/openclaw/dev/hermes-stuff/plugins/hermes-gizmo
pip install -e ".[dev]"
```

## 2. Add configuration

Create `$HERMES_HOME/config.yaml`:

```yaml
plugins:
  enabled:
    - tool-slimmer

tool_slimmer:
  enabled: true
  mode: keyword
  top_k: 8
  always_include:
    - terminal
    - read_file
    - write_file
    - patch
    - search_files
  always_exclude: []
  min_total_tools: 0
  min_estimated_reduction_percent: 5.0
  fail_open: true
  dry_run: true
```

Start with `dry_run: true`. This lets you inspect selections without changing provider requests.

### Mode choice

| Mode | When to use |
|---|---|
| `keyword` | Default. Fast, no extra deps. Uses BM25 ranking. |
| `hybrid` | Same as keyword plus a small fuzzy-token boost for typos. Negligible overhead. |
| `semantic_hybrid` | Only when a real embedding provider is available. With the default FakeEmbeddingProvider, it degrades to deterministic but semantically meaningless embeddings — lower quality than keyword. See `docs/gizmo-eval-report.md`. |
| `eager` | Sends full catalog; useful for debugging. |
| `anthropic_tool_search` | Only for Anthropic native provider with Tool Search support. |

## 3. Check installation

```bash
hermes tool-slimmer doctor
hermes tool-slimmer status
```

`doctor` reports whether:
- config is valid
- the plugin is enabled in the active profile
- index directory is writable
- the core selector hook is available

If `core_selector_hook` shows `warn`, your Hermes core does not advertise `select_tool_schemas`. The plugin will run diagnostics-only (dashboard/CLI work, no active slimming).

## 4. Preview selection

```bash
hermes tool-slimmer select "search this repo for MCP registration code" --schemas examples/tools.yaml
```

## 5. Enable active schema slimming

Set `dry_run: false` only after `doctor` reports all checks passing and you have observed satisfactory selections during dry-run.

## 6. Run the benchmark report

```bash
hermes tool-slimmer eval --prompts examples/prompts.yaml --schemas examples/tools.yaml --markdown
```

For a full mode comparison (keyword vs hybrid vs semantic_hybrid), see [`docs/gizmo-eval-report.md`](docs/gizmo-eval-report.md).

## Non-authorizations

- No upstream PR submission from this fork.
- No public package publish.
- No live default Hermes plugin install/enablement.
- No gateway restart unless explicitly approved.
- No provider credential changes.
- No destructive mutation of existing Tool Slimmer/Hermes installs.

See [`docs/gizmo-compatibility.md`](docs/gizmo-compatibility.md) for the full compatibility guide.
