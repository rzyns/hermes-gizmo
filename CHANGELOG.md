# Changelog

## 0.4.4 - 2026-05-19

Dashboard index reliability release.

### Fixed

- Dashboard "Rebuild From Hermes Tools" now chooses the largest available runtime catalog between Hermes tool definitions and the last live request snapshot.
- Dashboard rebuild now preserves an existing larger index instead of replacing it with a smaller standalone catalog, preventing full gateway catalogs from shrinking after cron/subagent snapshots or incomplete standalone `model_tools` discovery.

## 0.4.3 - 2026-05-19

Installer reliability release.

### Changed

- Prefer the Hermes virtualenv launcher at `$HOME/.hermes/hermes-agent/venv/bin/hermes` when install and troubleshooting scripts need a Hermes executable.
- Document the venv launcher path for Hermes Agent-assisted installs and repairs.
- Run the troubleshooting script through `bash` from the installer so executable-bit restrictions do not block the final health report.

## 0.2.0 - 2026-05-15

Dashboard and operations release.

### Added

- Hermes dashboard plugin with status, health checks, recent selection decisions, selected-tool visibility, and estimated schema-token savings.
- Dashboard backend API routes for Tool Slimmer status, session-filtered summaries, full audit summaries, and raw recent events.
- Durable JSONL decision logging under `$HERMES_HOME/tool-slimmer/decisions.jsonl`.
- One-command local installer/repair script and deterministic troubleshooting report script.
- GitHub Actions test workflow plus README badges and professional README hero image.

### Changed

- Dashboard headline totals now exclude probe/test events without a Hermes `session_id`; full audit totals remain available as `all_summary`.
- README and docs now clearly label savings as estimated schema-token savings, not guaranteed billable-token savings.

### Tested

- Added tests for decision logging, session-filtered summary accounting, dashboard API routes, and existing selector/provider behavior.

## 0.1.0 - 2026-05-03

Initial public release.

### Added

- Hermes plugin entry point `tool-slimmer`.
- Deterministic tokenizer, corpus builder, local BM25 ranker, and selector.
- Config loader for `tool_slimmer` settings in Hermes config files.
- CLI commands for status, doctor, index, select, benchmark, and config recommendations.
- Slash command and JSON tool handlers.
- Metrics for schema byte/token reduction estimates.
- Anthropic Tool Search helpers with explicit provider capability gating.
- JSON index store with checksum-based rebuilds.
- Upstreamable Hermes core selector-hook patch artifact.
- Documentation, examples, and unit tests.
