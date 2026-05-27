# Changelog

## 0.5.0 - 2026-05-27

Guided setup and profile tuning release.

### Added

- Platform profiles for Telegram, Slack, CLI/TUI, cron, and webhook entry points.
- Advisor recommendations with plain-English setup checklist, recommended YAML, safe apply, config backups, and rollback support.
- Dashboard Guided Setup card with one-click recommended config apply and backup visibility.
- Low-information query handling so greetings, pings, thanks, and numeric nudges do not fill `top_k` with unrelated task tools.
- Beginner-friendly setup docs and an agent-install prompt for users who do not want to run shell commands manually.

### Changed

- `always_exclude` is accepted as a user-facing alias for `disabled_tools`.
- Dashboard status now exposes disabled tools, disabled toolsets, aliases, and profiles for easier troubleshooting.

## 0.4.7 - 2026-05-20

Missing skill-tool fallback release.

### Fixed

- Full-tool fallback now survives the first user retry after `tool_slimmer_request_full_tools`, covering the common chat flow where the model asks the user to send another message before retrying.
- Ambiguous retry messages now use recent assistant/tool mentions of known tool names, so a follow-up like `12` can still expose a recently requested tool such as `skill_view`.
- Skill companion tools are kept together: selecting `skill_manage` or skill-context requests also keeps `skill_view` and `skills_list` available when present.

## 0.4.6 - 2026-05-19

Dashboard git-install compatibility release.

### Changed

- The repository root now includes the Hermes runtime plugin entry point and dashboard files, matching Hermes dashboard git-install expectations.
- Git checkouts installed at `$HERMES_HOME/plugins/tool-slimmer` now stay clean after repair, so the dashboard can show `Source: git` and keep using `git pull`.
- Mypy configuration now uses explicit package bases so the root Hermes plugin entry point can coexist with the `src/` Python package layout.

## 0.4.5 - 2026-05-19

Dashboard installer compatibility release.

### Changed

- The installer now supports being run from an in-place dashboard git checkout at `$HERMES_HOME/plugins/tool-slimmer` by overlaying the runtime plugin files without deleting the checkout, preserving future `git pull` updates from the plugin page.
- Plugin and dashboard manifest versions now track the package release version.

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
