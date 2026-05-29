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

The installer handles the Python package, dashboard files, Hermes plugin enablement, Hermes core selector hook, service restart, and final verification. Its core patcher supports both older monolithic Hermes cores and the current v0.14.0 modular core layout.

If it finishes successfully, run:

```bash
hermes tool-slimmer doctor
```

All checks should pass. If the dashboard is running, the Tool Slimmer tab should appear after the dashboard service restarts.

### Updating Hermes Later

Use the bundled helper when Hermes releases a new version:

```bash
scripts/update-hermes-and-repair-tool-slimmer.sh
```

This runs `hermes update --yes`, which answers Hermes' local-change restore prompt automatically. It keeps Hermes' normal backup behavior by default, then reruns the Tool Slimmer repair installer so the selector hook is reapplied if Hermes changed its request path. Pass `--no-backup` only if you intentionally want to skip Hermes' pre-update backup.

For automatic repair after future reboots or Hermes updates, enable the optional user service:

```bash
scripts/self-heal-tool-slimmer.sh --install-systemd
```

The service is intentionally narrow: it runs `doctor`, repairs only when Tool Slimmer is enabled and the core selector hook is missing, does not run network updates, and restarts only active Hermes services after a repair.

### If script execution is blocked

Some hosted agent environments block direct execution of downloaded scripts until the user approves that exact command. If Hermes reports that the repository downloaded correctly but `scripts/install-hermes-tool-slimmer.sh` was blocked, run the installer from a normal terminal or approve this command:

```bash
bash /tmp/hermes-tool-slimmer/scripts/install-hermes-tool-slimmer.sh
```

Use the actual unpacked repo path if it is not `/tmp/hermes-tool-slimmer`. This failure mode is an execution approval problem; the remaining install work is still the normal package install, plugin enablement, core patch check, service restart, and doctor report.

If there are multiple `hermes` launchers, prefer the venv launcher:

```bash
HERMES_BIN="$HOME/.hermes/hermes-agent/venv/bin/hermes" bash /tmp/hermes-tool-slimmer/scripts/install-hermes-tool-slimmer.sh
```

The source-checkout launcher may use system Python and fail to import packages installed into the Hermes venv.

If the approval layer asks what this command does, the answer is: installs the Python package into the Hermes virtual environment, copies the dashboard plugin into `~/.hermes/plugins/tool-slimmer`, enables the plugin, applies the Hermes selector-hook patch when needed, restarts Hermes dashboard/gateway services when present, and runs `doctor`.

### If Hermes Agent is installing it for you

Give Hermes Agent this prompt:

```text
Install Hermes Tool Slimmer from https://github.com/alias8818/hermes-tool-slimmer.
After downloading the repo, run:
HERMES_BIN="$HOME/.hermes/hermes-agent/venv/bin/hermes" bash /tmp/hermes-tool-slimmer/scripts/install-hermes-tool-slimmer.sh
If the environment asks for approval to run that script, request approval for that exact command.
Then verify with:
$HOME/.hermes/hermes-agent/venv/bin/hermes tool-slimmer doctor
```

If Hermes Agent says it downloaded or unpacked the repo but installation is not complete, the next step is usually only the `bash /tmp/hermes-tool-slimmer/scripts/install-hermes-tool-slimmer.sh` command above.
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

Experimental `mode: two_pass` is for large catalogs or TPM-capped providers. The first request gets only always-included tools plus `tool_slimmer_hydrate_tools`, whose schema contains a compact deterministic catalog. If the model needs tools, it asks for multiple full schemas in one hydration batch and the next request exposes only those schemas. Start with `keyword`; switch to `two_pass` only when the extra round trip is worth the schema savings.

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
