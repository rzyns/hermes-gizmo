# Hermes Dashboard Plugin

Hermes Tool Slimmer includes a dashboard plugin for visibility into selector activity, estimated schema-byte savings, and approximate schema-token savings.

## One-command install

```bash
scripts/install-hermes-tool-slimmer.sh
```

That script:

- installs this package into the Hermes Python environment
- copies the dashboard/user plugin into `$HERMES_HOME/plugins/tool-slimmer`
- enables `tool-slimmer` with `hermes plugins enable tool-slimmer`
- patches Hermes core with the `select_tool_schemas` hook when it is missing
- restarts `hermes-dashboard.service` and `hermes-gateway.service` when they exist
- runs a final health report

If you only want a health report:

```bash
scripts/troubleshoot-hermes-tool-slimmer.sh
```

## Manual install

Use this only when you cannot run the installer:

```bash
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python -e .
rm -rf ~/.hermes/plugins/tool-slimmer
cp -R dashboard-plugin/tool-slimmer ~/.hermes/plugins/tool-slimmer
hermes plugins enable tool-slimmer
systemctl --user restart hermes-dashboard.service hermes-gateway.service
hermes tool-slimmer doctor
```

Hermes mounts plugin API routers during dashboard startup; a plugin rescan can discover assets, but it does not mount a newly added `plugin_api.py`.

The dashboard reads from `$HERMES_HOME/tool-slimmer/decisions.jsonl`. Decision logging is enabled when `tool_slimmer.log_decisions: true`, which is the default. Logged records contain selector metrics, provider/model/platform/session metadata, and selected tool names; they do not store user prompts.

The dashboard includes a privacy card backed by the same field inventory as `hermes tool-slimmer privacy`. It also exposes score details for recent v0.3.0+ decisions in the Decision Inspector and can generate the bundled example eval report from the Release Evidence card.

## Tool Index

The dashboard has a **Tool Index** card that shows the persisted index path, rebuild state, indexed tool count, checksum, last-updated time, and a preview of indexed tool names. Use **Rebuild From Hermes Tools** after adding or removing Hermes plugins or MCP toolsets.

The persisted index is an operator aid. Live Hermes requests still rank the request-local tool schemas in memory, so the selector always respects the exact tools Hermes made available for that turn.

## Metrics Caveat

The dashboard reports estimated schema-token savings, not guaranteed billable-token savings. The estimate is `serialized tool-schema JSON bytes / 4` before and after Tool Slimmer selection. Actual provider input tokens can differ because model tokenizers, message formatting, prompt caching, system prompts, conversation history, and provider-specific tool serialization are outside this estimate.

Headline dashboard totals count real Hermes session events by default. Events without a `session_id` are treated as probes/tests and excluded from headline totals; the backend still returns `all_summary` for full audit visibility.

The dashboard also reports average selector overhead in milliseconds and the number of low-value selections skipped by the guardrails. Skips are expected for small cron catalogs or any request where estimated reduction is below `tool_slimmer.min_estimated_reduction_percent`.

## Troubleshooting

Run:

```bash
scripts/troubleshoot-hermes-tool-slimmer.sh
```

The last line is written for operators:

- `Ready` means the package, plugin, dashboard manifest, and core hook are in place.
- `Usable with warnings` usually means no schema file was supplied to validate `always_include`; this is acceptable after install.
- `Needs attention` lists failing checks that must be fixed.
