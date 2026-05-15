# Quickstart

## 1. Install

```bash
scripts/install-hermes-tool-slimmer.sh
```

The installer handles the Python package, dashboard files, Hermes plugin enablement, Hermes core selector hook, service restart, and final verification.

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
  min_total_tools: 20
  min_estimated_reduction_percent: 5.0
  fail_open: true
  dry_run: true
```

Start with `dry_run: true`. This lets you inspect selections without changing provider requests.

`min_total_tools` and `min_estimated_reduction_percent` are low-overhead guardrails. `min_total_tools` skips catalogs with fewer than that many tools; equality is allowed to slim. These guardrails are especially useful for cron jobs and other short tool catalogs where the schema savings may not justify changing the request.

## 3. Check installation

```bash
hermes tool-slimmer doctor
hermes tool-slimmer status
hermes tool-slimmer privacy
scripts/troubleshoot-hermes-tool-slimmer.sh
```

`doctor` reports whether Hermes is importable, the plugin is enabled, the index path is writable, and whether the core selector hook is available.

Dashboard savings are estimated schema-token savings, not invoice-grade billing numbers. They use serialized tool-schema JSON bytes divided by 4 before and after selection.

Open the Hermes dashboard and use Tool Slimmer's **Tool Index** card to rebuild the index from the currently enabled Hermes tools. This is the easiest way to confirm what the plugin sees after installing or changing toolsets.

Run `hermes tool-slimmer eval --prompts examples/prompts.yaml --schemas examples/tools.yaml --markdown` to reproduce the public example evaluation report.

## 4. Preview selection

```bash
hermes tool-slimmer select "search this repo for MCP registration code" --schemas tools.yaml
```

A schema file can be a YAML list or an object containing `tools:` / `schemas:`.

## 5. Enable active schema slimming

Set `dry_run: false` only after `doctor` reports a Hermes core selector hook or after applying the patch in `docs/hermes-core-selector-hook.patch` to Hermes core.

The installer patches the local Hermes core automatically when that hook is missing. Use `scripts/install-hermes-tool-slimmer.sh --no-core-patch` only when you want to manage Hermes core changes yourself.
