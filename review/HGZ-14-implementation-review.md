# HGZ-14 Independent Hermes Gizmo Implementation Review

Verdict: BLOCK

## Scope

Reviewed branch `janusz/hermes-gizmo` at `52f8b1944b138bc896819317be6445ae8e08ddf0` against pinned base `origin/main` / `c975b555b15fe78f36232734ccfe65e6606b85b5`.

Review scope from the task: branch/worktree, commits, tests/evals, installability, docs, privacy/logging, fail-open behavior, disabled-tool enforcement, absence of generic broker bypass, and non-authorizations.

Explicit non-claims: this review does not authorize upstream PR submission, publishing, default-profile enablement, gateway restart, credential changes, destructive mutation, or generic hidden-tool broker execution.

## Evidence inspected

- `git status --short --branch` in `/home/openclaw/dev/hermes-stuff/plugins/hermes-gizmo`: clean branch `janusz/hermes-gizmo` before report creation.
- `git log origin/main..HEAD --oneline`: three implementation commits:
  - `f8c9f6d feat(selector): add semantic_hybrid mode with RRF, embedding cache, and fallback`
  - `b3f2955 feat(progressive): add tool_slimmer_tool_search, tool_slimmer_tool_details, and session-loaded tools`
  - `52f8b19 docs+lint: Hermes Gizmo fork packaging, compat, and eval integration`
- `git diff --stat origin/main...HEAD`: 14 files changed, including `embeddings.py`, `session_tools.py`, `selector.py`, docs, and tests.
- Automated checks rerun locally with the repo venv:
  - `.venv/bin/python -m pytest tests/ --tb=short` -> `175 passed, 7 skipped in 1.59s`
  - `.venv/bin/python -m ruff check .` -> `All checks passed!`
- Parent HGZ-13 smoke handoff reported isolated-profile install, CLI import, and `175 passed, 7 skipped` at the same target commit.
- Manual code inspection of:
  - `src/hermes_tool_slimmer/session_tools.py`
  - `src/hermes_tool_slimmer/embeddings.py`
  - `src/hermes_tool_slimmer/selector.py`
  - `src/hermes_tool_slimmer/integration.py`
  - `src/hermes_tool_slimmer/schemas.py`
  - `src/hermes_tool_slimmer/metrics.py`
  - `tests/test_session_tools.py`
  - `tests/test_embeddings.py`
  - README/security/compatibility docs and design artifacts.
- Independent probe using a temporary `HERMES_HOME` and `HERMES_CONFIG` with `progressive_enabled: true` and `disabled_toolsets: [github]` showed `tool_slimmer_tool_search` returned `github_search_code` as `disabled: false, can_load: true`, and `tool_slimmer_tool_details({name: github_search_code, load: true})` returned `ok: true, load_action: added` and wrote it into session state.

## Blocking findings

### B1. Progressive loading does not enforce disabled toolsets in the model-facing search/details tools

Severity: blocking safety/contract failure

Evidence:
- Security expectation says disabled tools and disabled toolsets must never be reintroduced by the plugin: `SECURITY.md:22-23`.
- Progressive design requires `tool_slimmer_tool_details` to reject `disabled_toolsets`, `include_mcp_tools == False`, and `include_native_tools == False`; it also requires `tool_slimmer_tool_search` to omit disabled tools: `architecture/progressive-loading-design.md:293-303`.
- Implementation helper `_is_disabled_or_excluded()` only checks `cfg.disabled_tools` and explicitly says toolset-level exclusion cannot be checked without the schema: `session_tools.py:159-165`.
- But both search and details do have the schema at the call site (`schema = by_name[name]` in details; ranked schema iteration in search), and still use only the name-only helper: `session_tools.py:235-241`, `252-258`, `301-330`.
- Independent temp-config probe demonstrated the bug: with `disabled_toolsets: [github]`, `github_search_code` was reported as loadable and was added to the session-loaded state.

Impact:
- This is a direct failure of the disabled-tool enforcement requirement in the review task.
- Even though `integration._inject_session_loaded()` later filters disabled toolsets before provider-request injection, the model-facing `tool_search` / `tool_details` surface gives false permission and records a disabled-toolset entry as loaded. That is unsafe behavior for a tool whose security contract says disabled toolsets must not be reintroduced and whose design says `tool_details` prevents config circumvention.

Required repair:
- Make eligibility checking schema-aware and shared with selector eligibility semantics: `disabled_tools`, `disabled_toolsets`, `include_mcp_tools`, `include_native_tools`, and duplicate-name ambiguity.
- Ensure `tool_slimmer_tool_search` omits or hard-marks ineligible tools consistently with the frozen design.
- Ensure `tool_slimmer_tool_details(load=True)` rejects ineligible tools before mutating state.
- Add regression tests with an actual config file / environment path for disabled toolsets, MCP/native filters, and `load=True` mutation prevention.

### B2. Progressive session state is not session-scoped and materially deviates from the frozen design

Severity: blocking reliability/isolation failure

Evidence:
- Frozen design requires `SessionLoadedState(session_id=...)`, in-memory process-local state keyed by `session_id`, `LoadedToolEntry` with schema/toolset/source/last_used/use_count, load history, and anonymous-session isolation: `architecture/progressive-loading-design.md:55-69`, `188-210`, `288-289`, `332-386`.
- Implementation stores only `{name: loaded_at, expires_at}` in one file at `$HERMES_HOME/tool-slimmer/session_loaded.json`: `session_tools.py:29-45`, `72-85`.
- `select_tool_schemas_callback()` receives `session_id`, but `_inject_session_loaded()` ignores it and constructs `SessionLoadedState(...)` without a session key: `integration.py:156-165`, `331-339`.
- The implemented eviction is oldest-by-loaded-at only; no `last_used_at`, `use_count`, LRU, load history, explicit requested-this-turn priority, or `max_effective_tools` cap exists: `session_tools.py:97-109`, `integration.py:331-362`.
- `tests/test_session_tools.py:156-164` and `186-196` explicitly skip tool-level config/state integration and test only direct `SessionLoadedState` behavior, leaving the core progressive integration path under-tested.

Impact:
- Loaded tools leak across all conversations in the same profile/HERMES_HOME until TTL expiry, contrary to session-local design and the task's "session-loaded" claim.
- Missing LRU/use-count/history/cap behavior means the implementation does not satisfy the accepted progressive-loading architecture, even though the smoke suite passes.
- This can cause cross-conversation tool exposure and hard-to-debug selection changes in long-lived profiles.

Required repair:
- Key loaded state by `session_id` received by the selector hook and exposed tool handlers, with safe anonymous-session behavior.
- Either implement the frozen in-memory lifecycle or explicitly produce a new approved design delta before keeping file-backed profile-global state.
- Add tests for two session IDs, missing session IDs, TTL cleanup, LRU eviction, `max_effective_tools`, and selector merge isolation.

### B3. Semantic embedding cache can reuse stale vectors across providers/models and does not match the approved cache contract

Severity: blocking correctness/eval-integrity failure for `semantic_hybrid`

Evidence:
- Preflight contract required cache hit/miss keyed by per-tool `text_hash` with catalog checksum provenance in eval manifests: `preflight/implementation-contract.md:129-137`.
- Semantic design specifies `EmbeddingVector` metadata including `text_hash`, `backend_name`, `model_id`, and `dimensions`, and explains why `text_hash` is used instead of full schema checksum: `architecture/semantic-hybrid-design.md:38-50`.
- Implementation instead stores one `{checksum}.npz` matrix and a sidecar JSON containing only `tools` and `dim`: `embeddings.py:168-217`.
- `SemanticRanker.embed_documents()` calls `cache.load(checksum, tool_names, self.provider.dim)` and will reuse the matrix whenever schema checksum, tool order, and dimension match, regardless of provider backend, model ID, base URL, or fake-vs-real provider: `embeddings.py:257-271`.

Impact:
- Switching from fake embeddings to a real OpenAI-compatible provider with the same dimension, or switching between same-dimension embedding models, can silently reuse stale vectors from the previous backend/model.
- Eval results and production ranking can become provenance-incorrect while still appearing cache-valid.
- This undermines the evidence value of `docs/gizmo-eval-report.md` and any later semantic-hybrid smoke if cache state is shared.

Required repair:
- Include backend/provider identity, model ID, dimension, and canonical text hashes in cache metadata and validation.
- Add tests proving cache miss on provider/model changes with the same schema checksum/dim, and reuse only when canonical text hash + provider/model identity match.

### B4. `tool_slimmer_select` schema does not expose the implemented `semantic_hybrid` mode

Severity: blocking API/schema consistency failure

Evidence:
- `ToolSlimmerConfig.VALID_MODES` includes `semantic_hybrid`: `config.py:13`.
- The implementation and docs advertise `semantic_hybrid` as a selectable mode.
- The public `tool_slimmer_select` tool schema still restricts `mode` to `eager`, `keyword`, `hybrid`, and `anthropic_tool_search`, excluding `semantic_hybrid`: `schemas.py:7-16`.

Impact:
- The tool schema presented to the model/provider rejects or discourages one of the new implemented modes.
- This is especially important because `tool_slimmer_select` is the standalone diagnostic surface used when the selector hook is absent.

Required repair:
- Add `semantic_hybrid` to the schema enum and add a regression test that schemas and config `VALID_MODES` stay synchronized.

## Non-blocking observations

- Automated pytest and ruff evidence is good as far as it goes, and the parent isolated-profile smoke provides useful installability evidence.
- Fail-open behavior is mostly preserved in the callback: selector exceptions return `None` when `cfg.fail_open` is true (`integration.py:309-313`), and semantic embedding failure degrades to keyword (`selector.py:131-138`).
- I did not find a generic hidden-tool broker execution path: `tool_slimmer_tool_details` returns schemas / writes loaded state; it does not invoke arbitrary hidden tools.
- Privacy/logging looks mostly bounded: decision logs include provider/model/platform/session metadata, selected tool names, score details, candidates, and expanded query tokens, but not raw user prompts (`metrics.py`, `integration.py:268-304`). Docs disclose this in `docs/privacy.md`.
- Non-authorizations appear respected in this review: no upstream push, no public publish, no default-profile plugin enablement, no gateway restart, no credential change, and no destructive mutation were observed.

## Evidence audit summary

- Task / board: `t_39fb41c0` / `hermes-gizmo`
- Claim scope: independent implementation readiness and safety review for the Hermes Gizmo branch at commit `52f8b1944b138bc896819317be6445ae8e08ddf0`.
- Explicit non-claims: no deployment, publication, default-profile enablement, upstream submission, or live runtime mutation approved.
- Strongest evidence depth: local source inspection, local command evidence, parent smoke metadata, targeted independent temp-config probe.
- MechanicalVerdict: PASS — repo, branch, tests, and source files were inspectable; review artifact produced.
- SubstantiveVerdict: UNSUPPORTED — implementation does not satisfy disabled-tool enforcement, session isolation, cache provenance, and schema/API consistency requirements.
- Recommendation: REQUEST_REPAIR_OR_MORE_EVIDENCE.

## Final verdict

BLOCK

The branch is not ready for integration approval. Passing tests and install smoke do not cover multiple safety-critical contract gaps. Repair should focus first on disabled-toolset enforcement in progressive loading and true session-scoped state, then cache provenance and schema synchronization, followed by fresh targeted tests and a new independent re-review.
