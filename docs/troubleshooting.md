# Troubleshooting

## Installer script is blocked

If Hermes or an agent says the Tool Slimmer repo downloaded correctly but the installer script was blocked, this is usually an execution approval issue. Run the same command from a normal terminal on the Hermes machine:

```bash
bash /tmp/hermes-tool-slimmer/scripts/install-hermes-tool-slimmer.sh
```

If the repo is somewhere else, replace `/tmp/hermes-tool-slimmer` with that path. The installer performs the remaining normal steps: package install, dashboard plugin copy, plugin enablement, selector-hook patch check, service restart, and `hermes tool-slimmer doctor`.

Using `bash ...` avoids needing the script executable bit. If the environment still blocks it, approve that exact command in the approval prompt.

If Hermes Agent is handling the install, tell it:

```text
The repo is downloaded. Continue by running:
bash /tmp/hermes-tool-slimmer/scripts/install-hermes-tool-slimmer.sh
If this command is blocked, request approval for that exact command.
After it runs, verify with:
hermes tool-slimmer doctor
```

## Dashboard savings look too high

Dashboard savings are estimated schema-token savings, not guaranteed billable-token savings. Tool Slimmer computes them from serialized tool-schema JSON bytes divided by 4 before and after selection. Actual provider input-token and billing deltas can differ because tokenizers, prompt caching, system prompts, conversation history, and provider-specific tool serialization are outside this estimate.

The dashboard headline excludes probe/test events that do not have a Hermes `session_id`. Use the dashboard API's `all_summary` field when you need a full audit of every logged decision.

## No reduction occurs

Run `hermes tool-slimmer doctor`. If the core selector hook is unavailable, Hermes Tool Slimmer can benchmark and log dry-run decisions but cannot replace schemas sent to providers.

On Hermes Agent v0.14.0, use Tool Slimmer v0.4.0 or newer and rerun `scripts/install-hermes-tool-slimmer.sh` so the installer applies the modular core patch. Older Tool Slimmer releases targeted the previous `run_agent.py` request path and will not actively slim v0.14.0 provider requests.

Also check `tool_slimmer.min_total_tools` and `tool_slimmer.min_estimated_reduction_percent`. By default, Tool Slimmer ranks even small catalogs (`min_total_tools: 0`) so subagents and restricted toolsets still benefit, then skips ranked selections under 5% estimated schema reduction. Raise `min_total_tools` only for cron/small-toolset paths where the overhead is not worth the tiny savings.

In `anthropic_tool_search` mode, reduction metrics and the reduction guardrail use the hot set of immediately loaded tools. The dashboard still records Anthropic payload and deferred-tool counts so you can confirm defer loading is active.

If the standalone `tool_slimmer_select` tool reports `no_schemas_available`, rebuild the index from the dashboard or run it inside a Hermes process where live tool definitions are importable. The tool reports `schema_source` as `provided`, `live`, or `index` when selection succeeds.

## Tool index looks stale

Open the Tool Slimmer dashboard page and click **Rebuild From Hermes Tools**. The card shows the index path, count, checksum, and last-updated time. The live selector still ranks the current request's tool schemas in memory, so a stale persisted index affects visibility and troubleshooting, not request-time safety.

## A required tool is missing

Ask the model to call `tool_slimmer_request_full_tools`, or add the tool to `tool_slimmer.always_include` if it should stay loaded on every request. The fallback tool marks the conversation so the next model request receives the full Hermes schema list and can retry the original action. The selector never resurrects tools that Hermes already disabled.

In keyword mode, the selector mostly matches text present in tool names, toolsets, descriptions, and parameter schemas. It includes a small built-in synonym map for common browser/navigation wording, but domain-specific synonyms should still be added to tool descriptions or handled by a semantic selector mode when one is available.

`hybrid` mode adds a deterministic fuzzy-token boost on top of keyword ranking. It is intended for close spelling/wording misses, not broad semantic reasoning.

`always_include` is intentionally outside the `top_k` budget. For example, five always-included tools plus `top_k: 8` can return up to thirteen selected tools.

`top_k: 0` is a valid explicit setting for selecting no ranked tools. It does not trigger fail-open by itself.

## Selector errors

Keep `fail_open: true` for normal use. Errors then preserve the original full schema list.
