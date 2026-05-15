# Hermes Tool Slimmer

[![Tests](https://github.com/alias8818/hermes-tool-slimmer/actions/workflows/tests.yml/badge.svg)](https://github.com/alias8818/hermes-tool-slimmer/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776ab)
![Ruff](https://img.shields.io/badge/lint-ruff-46a2f1)
![License](https://img.shields.io/badge/license-MIT-green)
![Hermes](https://img.shields.io/badge/Hermes-dashboard%20plugin-111827)

![Hermes Tool Slimmer dashboard hero](docs/assets/tool-slimmer-hero.png)

Hermes Tool Slimmer reduces repeated tool-schema overhead by selecting the smallest useful tool set for a turn. It builds an indexable corpus from Hermes tool schemas, ranks candidate tools with local BM25 plus explicit boosts, and fails open to the original schema list when anything goes wrong.

## Why

Large Hermes installations can expose dozens of native and MCP tools. A 57-tool schema catalog can serialize to roughly 73 KB, or about 18K approximate prompt tokens using the documented `bytes / 4` estimate. Selecting 8-12 relevant tools for a repository-search turn can reduce that to about 15 KB / 3.7K approximate tokens while keeping configured safety tools hot.

Tool slimming is only a schema-selection optimization. It must not bypass Hermes approval prompts, tool execution controls, provider auth, disabled toolsets, or any runtime safety policy.

## What The Numbers Mean

The dashboard reports **estimated schema tokens saved**, not guaranteed billable-token savings. The estimate is computed from serialized tool-schema JSON bytes divided by 4 before and after selection. Provider tokenizers, prompt formatting, cache behavior, system prompts, conversation history, and model-specific tool serialization can make actual input-token and billing deltas differ.

The metric is still useful because it measures the repeated tool-catalog payload that Tool Slimmer removes from each request. Treat it as a consistent operational estimate for schema overhead, not as an invoice-grade accounting number.

Dashboard headline totals count real Hermes session events by default. Probe events without a `session_id` are excluded from headline savings and remain available through the dashboard API's `all_summary` field for audits.

## Install

```bash
scripts/install-hermes-tool-slimmer.sh
```

That handles the package install, dashboard plugin copy, Hermes plugin enablement, selector-hook patch, service restart, and final health report.

For a guided setup, see [`docs/quickstart.md`](docs/quickstart.md). For the Hermes dashboard page, see [`docs/dashboard-plugin.md`](docs/dashboard-plugin.md).

The dashboard includes a **Tool Index** panel with a one-click **Rebuild From Hermes Tools** action, indexed-tool preview, path, checksum, and last-updated time. The persisted index is for inspection and troubleshooting; live slimming ranks the current request's Hermes schemas in memory.

For a plain-English health report:

```bash
scripts/troubleshoot-hermes-tool-slimmer.sh
```

For local development:

```bash
pip install -e ".[dev]"
pytest
```

## Quality Gates

The repository ships focused unit and integration tests for selector behavior, config validation, metrics accounting, dashboard API routes, and provider fallback behavior. Run the same checks used by CI locally:

```bash
ruff check .
python -m compileall -q src tests dashboard-plugin/tool-slimmer
pytest -q
```

## Configure

```yaml
plugins:
  enabled:
    - tool-slimmer

tool_slimmer:
  enabled: true
  mode: keyword        # eager | keyword | hybrid | anthropic_tool_search
  top_k: 8             # selected after always_include
  always_include: [terminal, read_file, write_file, patch, search_files]
  never_defer: [terminal, read_file]
  include_mcp_tools: true
  include_native_tools: true
  log_decisions: true
  min_total_tools: 20
  min_estimated_reduction_percent: 5.0
  aliases:
    browse: [browser, navigate, url, website]
  fail_open: true      # selector errors preserve the original full schema list
  dry_run: false       # true logs/injects diagnostics but does not alter schemas
```

## Commands

```bash
hermes tool-slimmer status
hermes tool-slimmer doctor
hermes tool-slimmer index rebuild --schemas examples/tools.yaml
hermes tool-slimmer index show --top 20
hermes tool-slimmer select "search this repo for MCP registration code" --schemas tools.yaml
hermes tool-slimmer benchmark --prompts examples/prompts.yaml --schemas examples/tools.yaml
hermes tool-slimmer eval --prompts examples/prompts.yaml --schemas examples/tools.yaml
hermes tool-slimmer eval --prompts examples/prompts.yaml --schemas examples/tools.yaml --markdown
hermes tool-slimmer analyze-config
hermes tool-slimmer privacy
hermes tool-slimmer recommend-config
```

Slash commands:

```text
/tool-slimmer status
/tool-slimmer select search this repo for MCP registration code
/tool-slimmer dry-run on
/tool-slimmer dry-run off
```

## Provider behavior

| Provider path | Behavior |
|---|---|
| Anthropic native | Tool Search/defer loading if `mode: anthropic_tool_search` and Hermes core supports the required request serialization/headers. |
| Bedrock/Vertex/Azure Anthropic | Attempt only when the Hermes provider stack supports the Anthropic Tool Search path for that provider/model. |
| OpenRouter/OpenAI/local | Fall back to deterministic keyword selection, hybrid when implemented, or eager mode according to config; do not send Anthropic-only Tool Search definitions. |

## Integration status

The standalone plugin registers diagnostics tools, slash commands, CLI commands, a dry-run `pre_llm_call` diagnostic hook, and a `select_tool_schemas` callback when Hermes core supports it.

Supported/target core surfaces:

- `ctx.register_tool_schema_selector(callback)`
- `ctx.register_schema_selector(callback)`
- `ctx.register_hook("select_tool_schemas", callback)`

If none exists, the plugin does not monkeypatch provider internals. It remains useful for dry-run diagnostics, benchmarking, and configuration recommendations until Hermes core exposes a selector hook. See `docs/hermes-core-selector-hook.patch` for a minimal upstreamable Hermes core patch artifact based on current source inspection.

## Safety model

- `always_include` tools are selected first when present and not already disabled by Hermes.
- `top_k` applies after `always_include`; always-included tools do not count against the `top_k` budget.
- `disabled_tools`, `disabled_toolsets`, `include_mcp_tools`, and `include_native_tools` are respected before ranking.
- `min_total_tools` skips catalogs with fewer than that many tools before ranking; equality is allowed to slim.
- `min_estimated_reduction_percent` fails open after ranking if the estimated schema reduction is too small to justify altering the request.
- `fail_open: true` sends the original schema list on selector errors.

Keyword mode is intentionally mostly literal. It includes a small deterministic synonym map for common operation words such as browsing/navigation, but tool-specific synonyms should still be added to tool descriptions or handled by a semantic selector mode when available.
- `aliases` extends keyword query expansion deterministically; aliases affect ranking and score details but do not rewrite stored tool schemas.
- `dry_run: true` logs decisions and returns `None` to preserve original behavior.
- Anthropic Tool Search helpers never defer every tool.


## Public release contents

- [`docs/quickstart.md`](docs/quickstart.md): install, dry-run, and activation walkthrough.
- [`docs/hermes-core-integration.md`](docs/hermes-core-integration.md): required Hermes core selector hook contract.
- [`docs/hermes-core-selector-hook.patch`](docs/hermes-core-selector-hook.patch): minimal upstreamable Hermes core patch artifact.
- [`docs/anthropic-tool-search.md`](docs/anthropic-tool-search.md): provider capability notes for Anthropic Tool Search.
- [`docs/privacy.md`](docs/privacy.md): decision log field inventory and privacy notes.
- [`docs/reports/latest-eval.md`](docs/reports/latest-eval.md): reproducible example evaluation report.
- [`docs/troubleshooting.md`](docs/troubleshooting.md): common operational issues.
- [`examples/`](examples/): sample config, prompts, schemas, and expected output.

## Release validation

This repository is release-ready only when these checks pass:

```bash
ruff check .
mypy src tests
python -m compileall -q src tests
pytest -q
python -m build
```

When changing the Hermes core patch, also run the validation steps in [`docs/release-checklist.md`](docs/release-checklist.md).
