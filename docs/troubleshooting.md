# Troubleshooting

## Dashboard savings look too high

Dashboard savings are estimated schema-token savings, not guaranteed billable-token savings. Tool Slimmer computes them from serialized tool-schema JSON bytes divided by 4 before and after selection. Actual provider input-token and billing deltas can differ because tokenizers, prompt caching, system prompts, conversation history, and provider-specific tool serialization are outside this estimate.

The dashboard headline excludes probe/test events that do not have a Hermes `session_id`. Use the dashboard API's `all_summary` field when you need a full audit of every logged decision.

## No reduction occurs

Run `hermes tool-slimmer doctor`. If the core selector hook is unavailable, Hermes Tool Slimmer can benchmark and log dry-run decisions but cannot replace schemas sent to providers.

## A required tool is missing

Add it to `tool_slimmer.always_include` or increase `top_k`. The selector never resurrects tools that Hermes already disabled.

## Selector errors

Keep `fail_open: true` for normal use. Errors then preserve the original full schema list.
