# HGZ-16 Fresh Independent Re-review of HGZ-14 Blocker Repairs

Verdict: BLOCK

## Scope

Reviewed `janusz/hermes-gizmo` in `/home/openclaw/dev/hermes-stuff/plugins/hermes-gizmo` at actual HEAD `717c4bbf294cd2cb1240eb9374041e43fbe373a0`, against pinned base `c975b555b15fe78f36232734ccfe65e6606b85b5` and prior HGZ-14 review commit `47422b7f3540822f71bb21b1501284ee449`.

This re-review checks the HGZ-14 blockers B1-B4 after repair card `t_f30ea37d`, plus regression evidence, full suite / ruff evidence, clean worktree, absence of hidden broker execution, and preservation of non-authorizations.

Explicit non-claims: this review does not authorize push, upstream PR, public package publish, live default-profile install/enablement, gateway restart, provider credential changes, destructive mutation of existing Tool Slimmer/Hermes installs, or generic hidden-tool broker execution. A PASS here would only have meant HG-02 could be asked for a final human decision; this review is BLOCK.

## Evidence inspected

- `git status --short --branch` before report creation: clean `janusz/hermes-gizmo` worktree.
- `git rev-parse HEAD`: `717c4bbf294cd2cb1240eb9374041e43fbe373a0`.
- `git log --oneline --decorate -8`: repair commit `717c4bb fix(HGZ-14): B1-B4 repair — progressive eligibility, session scope, cache provenance, schema sync` atop prior review commit `47422b7`.
- `git diff --stat 47422b7..HEAD`: 5 files changed, 969 insertions / 72 deletions.
- `git diff --stat c975b555b15fe78f36232734ccfe65e6606b85b5..HEAD`: 16 files changed, including the prior HGZ-14 review artifact and new `tests/test_hgz14_regressions.py`.
- Read prior HGZ-14 review artifact: `review/HGZ-14-implementation-review.md`.
- Source inspected:
  - `src/hermes_tool_slimmer/session_tools.py`
  - `src/hermes_tool_slimmer/integration.py`
  - `src/hermes_tool_slimmer/embeddings.py`
  - `src/hermes_tool_slimmer/schemas.py`
  - `src/hermes_tool_slimmer/config.py`
  - `tests/test_hgz14_regressions.py`
  - `tests/test_handlers_integration.py` around the failing full-suite test.
- Targeted checks run locally:
  - `.venv/bin/python -m pytest tests/test_hgz14_regressions.py --tb=short` -> `34 passed in 1.24s`.
  - Independent temp-state probe for disabled toolset/MCP search/details rejection and no mutation -> passed; disabled results were non-loadable, rejected load kept count at 0, session A loaded `terminal` while session B saw count 0.
  - Independent `_inject_session_loaded` probe -> session A merged `terminal`; session B did not.
  - Independent embedding cache provider/model switch probe -> first provider called once, changed model/provider called once, exact repeat reused cache with zero provider calls.
  - `.venv/bin/python -m ruff check .` -> `All checks passed!`.
- Full-suite check run locally:
  - `.venv/bin/python -m pytest tests/ --tb=short` -> `1 failed, 208 passed, 7 skipped in 2.82s`.

## B1 verification: disabled-toolset/native/MCP/filter enforcement

Status: repaired for the HGZ-14 contract.

Evidence:

- `session_tools._schema_is_eligible()` now checks schema type, `disabled_tools`, `disabled_toolsets`, MCP exclusion, and native exclusion before declaring a tool eligible (`session_tools.py:225-240`).
- `tool_slimmer_tool_search()` applies `_schema_is_eligible()` for both scored and appended results and marks ineligible tools `disabled: true` / `can_load: false`; ambiguous duplicates are also not loadable (`session_tools.py:335-372`).
- `tool_slimmer_tool_details(load=True)` computes eligibility before mutation, returns `tool_disabled` / `tool_ambiguous` for ineligible tools, and only calls `state.add()` after those checks (`session_tools.py:422-472`).
- Regression tests cover disabled tool, disabled toolset, MCP exclusion, native exclusion, duplicate-name ambiguity, rejected `load=True`, and no mutation on rejection (`tests/test_hgz14_regressions.py:35-238`).
- Independent probe output: `github_search_code` and `mcp_server_foo.tool_a` were disabled and not loadable; rejected `github_search_code` load produced `tool_disabled` and state count remained 0.

Notes:

- `tool_search` currently hard-marks ineligible tools rather than omitting them. That matches the prior HGZ-14 repair requirement as phrased in the review artifact (`omit or hard-marks ineligible tools`) and the current regression tests.

## B2 verification: session-scoped progressive state

Status: repaired for the HGZ-14 blocker as scoped, with one design caveat recorded below.

Evidence:

- `SessionLoadedState` accepts `session_id`; missing IDs map to `__anonymous__`; persisted state is versioned as `{version: 2, sessions: {session_id: {loaded_tools: ...}}}` and saves preserve sibling sessions (`session_tools.py:33-124`).
- Loaded entries now include `loaded_at`, `expires_at`, `last_used_at`, `use_count`, and `toolset` (`session_tools.py:21-31`, `session_tools.py:107-124`).
- TTL cleanup and LRU eviction are implemented (`session_tools.py:126-148`), and `add()` updates last-used/use-count before eviction (`session_tools.py:150-175`).
- Tool details/search/diagnostic handlers pass `session_id` into `SessionLoadedState` (`session_tools.py:326-333`, `session_tools.py:438-445`, `session_tools.py:489-494`).
- Selector merge receives the hook `session_id` and injects only the current session's loaded tools (`integration.py:305`, `integration.py:331-362`).
- Tests cover two named sessions, anonymous behavior, LRU, TTL, use counts, sibling-session preservation, diagnostic session isolation, and cross-session tool isolation (`tests/test_hgz14_regressions.py:240-381`, `tests/test_hgz14_regressions.py:540-573`).
- Independent `_inject_session_loaded` probe showed `sess-a` selection `['read_file', 'terminal']` and `sess-b` selection `['read_file']` from the same state file.

Caveat, not counted as a blocker here:

- Anonymous/missing-session calls share the explicit `__anonymous__` bucket. That is at least bounded and non-crashing, but it is not as isolated as named session IDs. The task asked for safe anonymous-session behavior; the current tests define this as a stable anonymous bucket rather than per-call ephemerality.

## B3 verification: embedding cache provenance

Status: repaired for the HGZ-14 contract.

Evidence:

- `EmbeddingProvider` now exposes `provider_id` and `model_id`; fake and OpenAI-compatible providers implement stable IDs, with OpenAI `provider_id` including base URL (`embeddings.py:33-57`, `embeddings.py:91-147`).
- `CacheProvenance` records schema checksum, provider ID, model ID, dimension, and canonical text hashes and derives the filesystem key from those fields (`embeddings.py:211-231`).
- `EmbeddingCache._validate_meta()` checks checksum, dimension, provider ID, model ID, and text hashes before returning cached vectors (`embeddings.py:268-280`, `embeddings.py:324-349`).
- `SemanticRanker.embed_documents()` builds provenance from `IndexStore.checksum(schemas)`, provider identity/model/dim, and per-schema canonical text hashes, then calls `cache.load(provenance)` / `cache.save(provenance, ...)` (`embeddings.py:438-460`).
- Tests cover provider miss, model miss, text-hash miss, exact hit, deterministic text hashes, and OpenAI base-URL provider identity (`tests/test_hgz14_regressions.py:383-520`).
- Independent provider/model-switch probe produced separate cache files and call counts `1 1 0`: changed model/provider missed cache and exact repeat hit cache.

Caveat, not counted as a blocker here:

- `EmbeddingCache.load()` / `save()` preserve a legacy checksum-only signature. The repaired `SemanticRanker` path no longer uses it. I did not find this to reintroduce the original stale-vector bug in the semantic-hybrid selection path, but the legacy API should be considered compatibility-only.

## B4 verification: `semantic_hybrid` schema exposure and drift guard

Status: repaired.

Evidence:

- `SELECT_SCHEMA` includes `semantic_hybrid` in the public `mode` enum (`schemas.py:7-16`).
- `VALID_MODES` includes `semantic_hybrid` (`config.py:13`).
- Regression tests assert schema inclusion, config inclusion, and exact schema/config enum synchronization (`tests/test_hgz14_regressions.py:522-537`).

## Hidden broker / non-authorization check

Status: no violation found in inspected repair.

Evidence:

- `tool_slimmer_tool_details()` returns schema/info and optionally mutates session-loaded state; it does not invoke arbitrary tools or execute hidden broker calls (`session_tools.py:390-479`).
- Repair diff touched `session_tools.py`, `integration.py`, `embeddings.py`, `schemas.py`, and regression tests; no push/publish/install/gateway/credential/destructive path was observed in code review or commands run.
- The commands run during this review were local git/pytest/ruff/probe commands only.

## Blocking finding

### B5. Full test suite fails in the reviewer environment

Severity: blocking release/review-gate evidence failure.

Evidence:

- Command: `.venv/bin/python -m pytest tests/ --tb=short` in `/home/openclaw/dev/hermes-stuff/plugins/hermes-gizmo`.
- Result: `1 failed, 208 passed, 7 skipped in 2.82s`.
- Failing test: `tests/test_handlers_integration.py::test_pre_llm_and_selector_hooks_registered`.
- Failure excerpt: `AssertionError: assert False is True`, where `maybe_register_selector_hook(Ctx())` returned `False`.
- Captured log excerpt: `Hermes selector hook is unavailable; tool-slimmer will run diagnostics only`.
- Environment probe showed the test is seeing live Hermes plugin hooks from `/home/openclaw/.hermes/hermes-agent/hermes_cli/plugins.py`; `VALID_HOOKS` does not include `select_tool_schemas`.

Impact:

- This contradicts the parent handoff's `pytest: 209 passed, 7 skipped` claim in this reviewer environment.
- Even though the four HGZ-14 blockers appear substantively repaired, I cannot issue PASS while the full suite fails under the normal local repo venv command.
- The failing test also touches selector-hook registration behavior, which is adjacent to the plugin's runtime integration surface. It is not safe to waive silently in a review gate.

Required repair:

- Make `test_pre_llm_and_selector_hooks_registered` deterministic with respect to installed/live `hermes_cli.plugins.VALID_HOOKS`, or adjust `maybe_register_selector_hook()` semantics and tests so the expected behavior is explicit when a ctx lacks its own `valid_hooks` but live Hermes exposes no `select_tool_schemas` hook.
- Re-run the full suite and ruff after repair and provide fresh evidence.

## Non-blocking evidence precision note

The parent task metadata advertised full commit SHA `717c4bbff7fd0ee5d57f28f44c7c2f62b9e6e9c9`, but `git rev-parse --verify 717c4bbff7fd0ee5d57f28f44c7c2f62b9e6e9c9^{commit}` failed. The actual reviewed HEAD is `717c4bbf294cd2cb1240eb9374041e43fbe373a0`. The abbreviated `717c4bb` still points to the intended repair commit, so this is not the substantive blocker; it is a handoff precision issue.

## Evidence audit summary

- Task / board: `t_98bbfe81` / `hermes-gizmo`.
- Claim scope: fresh independent re-review of HGZ-14 blocker repairs B1-B4 plus regression/ruff/full-suite/worktree/non-authorization evidence on `janusz/hermes-gizmo` at `717c4bbf294cd2cb1240eb9374041e43fbe373a0`.
- Explicit non-claims: no push, PR, publish, live install/enablement, gateway restart, credential change, destructive mutation, generic hidden-tool execution, or final human approval authorized.
- Strongest evidence depth: local source inspection, local git evidence, local targeted command evidence, local full-suite command evidence, independent temp-state/runtime probes.
- MechanicalVerdict: PASS for inspectability of the repo, repair diff, tests, and review artifact; PARTIAL for parent handoff precision because the advertised full SHA is not resolvable.
- SubstantiveVerdict: PARTLY_SUPPORTED. B1-B4 repairs are supported by source and targeted tests/probes, but the full-suite requirement is unsupported because the suite fails locally.
- Recommendation: REQUEST_REPAIR_OR_MORE_EVIDENCE.

## Final verdict

BLOCK
