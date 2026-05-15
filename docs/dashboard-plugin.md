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

## Metrics Caveat

The dashboard reports estimated schema-token savings, not guaranteed billable-token savings. The estimate is `serialized tool-schema JSON bytes / 4` before and after Tool Slimmer selection. Actual provider input tokens can differ because model tokenizers, message formatting, prompt caching, system prompts, conversation history, and provider-specific tool serialization are outside this estimate.

Headline dashboard totals count real Hermes session events by default. Events without a `session_id` are treated as probes/tests and excluded from headline totals; the backend still returns `all_summary` for full audit visibility.

## Troubleshooting

Run:

```bash
scripts/troubleshoot-hermes-tool-slimmer.sh
```

The last line is written for operators:

- `Ready` means the package, plugin, dashboard manifest, and core hook are in place.
- `Usable with warnings` usually means no schema file was supplied to validate `always_include`; this is acceptable after install.
- `Needs attention` lists failing checks that must be fixed.
