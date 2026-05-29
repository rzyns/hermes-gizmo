# Quickstart

## 1. Install

Use Tool Slimmer v0.4.0+ with Hermes Agent v0.14.0. Older Tool Slimmer releases are not functionally compatible with Hermes v0.14.0 active schema slimming because the provider request construction code moved.

### Dashboard Install

On Hermes builds with dashboard plugin repair support, open the dashboard **Plugins** page, paste this into the install field, and keep **Enable after install** on:

```text
alias8818/hermes-tool-slimmer
```

The dashboard installer clones the repo to `~/.hermes/plugins/tool-slimmer`, runs the Tool Slimmer repair installer with `--no-restart`, and preserves the git checkout so the dashboard **Update** button can use `git pull` later. Restart the gateway after install or update so active schema slimming uses the patched selector hook.

### Terminal Install

Open a terminal on the machine where Hermes is installed:

```bash
cd /tmp
git clone https://github.com/alias8818/hermes-tool-slimmer.git
cd hermes-tool-slimmer
```

Run the installer:

```bash
scripts/install-hermes-tool-slimmer.sh
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

Add a `tool_slimmer` section to `~/.hermes/config.yaml`:

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

`min_total_tools` and `min_estimated_reduction_percent` are low-overhead guardrails. `min_total_tools` skips catalogs with fewer than that many tools; equality is allowed to slim. The default is `0` so subagents and restricted toolsets are still ranked. Raise it only for paths where small catalogs are not worth changing.

Tool Slimmer keeps `tool_slimmer_request_full_tools` available in trimmed requests. If a skill needs a hidden tool, the model can call that fallback tool and the next model request will receive the full Hermes tool schema list.

Use `mode: keyword` first. `hybrid` only adds a deterministic fuzzy-token boost; it is not a semantic embedding mode. For broad general agents, keep `top_k` around `8`. For narrow Telegram or webhook processors, smaller values such as `4` can save more schema tokens, but add `always_include` for required tools and `always_exclude` for noisy tools such as `terminal` or `cronjob` when that entry point should never use them.

Experimental `mode: two_pass` is for large catalogs or TPM-capped providers. The first request gets only always-included tools plus `tool_slimmer_hydrate_tools`, whose schema contains a compact deterministic catalog. If the model needs tools, it asks for multiple full schemas in one hydration batch and the next request exposes only those schemas. Start with `keyword`; switch to `two_pass` only when the extra round trip is worth the schema savings.

## 3. Check installation

```bash
hermes tool-slimmer doctor
hermes tool-slimmer status
hermes tool-slimmer privacy
scripts/troubleshoot-hermes-tool-slimmer.sh
```

`doctor` reports whether Hermes is importable, the plugin is enabled, the index path is writable, and whether the core selector hook is available.

Dashboard savings are estimated schema-token savings, not invoice-grade billing numbers. They use serialized tool-schema JSON bytes divided by 4 before and after selection.

Open the Hermes dashboard and use Tool Slimmer's **Tool Index** card to rebuild the index from the currently enabled Hermes tools. Then use **Guided Setup** -> **Apply Recommended Config** to create platform profiles with a config backup. This is the easiest way to confirm what the plugin sees after installing or changing toolsets.

Run `hermes tool-slimmer eval --prompts examples/prompts.yaml --schemas examples/tools.yaml --markdown` to reproduce the public example evaluation report.

## 4. Preview selection

```bash
hermes tool-slimmer select "search this repo for MCP registration code" --schemas tools.yaml
```

A schema file can be a YAML list or an object containing `tools:` / `schemas:`.

## 5. Enable active schema slimming

Set `dry_run: false` only after `doctor` reports a Hermes core selector hook or after applying the patch in `docs/hermes-core-selector-hook.patch` to Hermes core.

The installer patches the local Hermes core automatically when that hook is missing. Use `scripts/install-hermes-tool-slimmer.sh --no-core-patch` only when you want to manage Hermes core changes yourself.
