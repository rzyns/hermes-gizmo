# HGZ-18 Fresh Independent Final Re-review after HGZ-16 B5 Repair

Verdict: PASS

## Scope

Reviewed `janusz/hermes-gizmo` in `/home/openclaw/dev/hermes-stuff/plugins/hermes-gizmo` after repair card `t_4eb6170a`.

Reviewed implementation HEAD before this report was written: `0613989bfa8b4cfe4d0bfa70ce70475ac9e5325d` (`fix(HGZ-16): make test_pre_llm_and_selector_hooks_registered deterministic wrt live VALID_HOOKS`). Pinned base: `c975b555b15fe78f36232734ccfe65e6606b85b5`.

This review checks whether HGZ-16 B5 is repaired, whether HGZ-14 B1-B4 remain substantively repaired, whether full pytest/ruff pass on current HEAD, whether the worktree is clean, whether a generic hidden-tool broker execution path exists, and whether non-authorized external actions remain unapproved/unperformed.

Explicit non-claims: PASS here only means HG-02 may be asked for an explicit final human decision. It does not authorize push, upstream PR, public package publish, live default-profile install/enablement, gateway restart, provider credential changes, destructive mutation of existing Tool Slimmer/Hermes installs, generic hidden-tool broker execution, or final human approval.

## Branch / commit evidence

Before this report was created:

- `git status --short --branch` showed clean branch `janusz/hermes-gizmo`.
- `git rev-parse HEAD` returned `0613989bfa8b4cfe4d0bfa70ce70475ac9e5325d`.
- `git branch --show-current` returned `janusz/hermes-gizmo`.
- `git log --oneline c975b555b15fe78f36232734ccfe65e6606b85b5..HEAD` returned:
  - `0613989 fix(HGZ-16): make test_pre_llm_and_selector_hooks_registered deterministic wrt live VALID_HOOKS`
  - `d678187 review: HGZ-16 repair re-review`
  - `717c4bb fix(HGZ-14): B1-B4 repair — progressive eligibility, session scope, cache provenance, schema sync`
  - `47422b7 review: HGZ-14 implementation review`
  - `52f8b19 docs+lint: Hermes Gizmo fork packaging, compat, and eval integration`
  - `b3f2955 feat(progressive): add tool_slimmer_tool_search, tool_slimmer_tool_details, and session-loaded tools`
  - `f8c9f6d feat(selector): add semantic_hybrid mode with RRF, embedding cache, and fallback`
- `git diff --name-only d6781878103dcddbf8f3074e3aac58f31dd1d9af..HEAD` showed only `tests/test_handlers_integration.py` changed since HGZ-16.
- `git show -- tests/test_handlers_integration.py` for `0613989` showed exactly two inserted lines: `Ctx.valid_hooks = {"pre_llm_call", "select_tool_schemas"}` in `test_pre_llm_and_selector_hooks_registered`.

## Automated checks run in this review

- `.venv/bin/python -m pytest tests/ --tb=short && .venv/bin/python -m ruff check .`
  - Result: `209 passed, 7 skipped in 2.80s`; `All checks passed!`.
- `.venv/bin/python -m pytest tests/test_handlers_integration.py::test_pre_llm_and_selector_hooks_registered -q --tb=short`
  - Result: `1 passed`.
- Independent selector-hook semantics probe:
  - Explicit context with `valid_hooks = {"pre_llm_call", "select_tool_schemas"}` returned `True` and registered `pre_llm_call`, then `select_tool_schemas`.
  - Explicit context with `valid_hooks = {"pre_llm_call"}` returned `False` and registered only `pre_llm_call`.
  - Output included `explicit-selector-hook true; explicit-no-selector false`.
- `.venv/bin/python -m pytest tests/test_hgz14_regressions.py tests/test_session_tools.py tests/test_embeddings.py -q --tb=short`
  - Result: command exited 0; progress output completed all selected tests.

## B5 verification: full-suite failure repaired deterministically

Status: repaired.

Evidence:

- HGZ-16 B5 failed because `test_pre_llm_and_selector_hooks_registered` used a test `Ctx` without `valid_hooks`, so `maybe_register_selector_hook()` fell back to the live installed Hermes `VALID_HOOKS`; in this reviewer environment, that live set did not include `select_tool_schemas`, causing the function to return `False` and the full suite to fail.
- Repair commit `0613989` changed only `tests/test_handlers_integration.py` and added an explicit `valid_hooks` set to that test context.
- The implementation still preserves fail-safe behavior when selector hooks are unavailable:
  - `integration.py:365-416` still checks known hook sets via `_known_valid_hooks()` and returns `False` without registering `select_tool_schemas` when the hook is absent.
  - `tests/test_handlers_integration.py:800-812` covers explicit `valid_hooks = {"pre_llm_call"}` and expects no selector registration.
  - `tests/test_handlers_integration.py:815-828` covers fallback to live `hermes_cli.plugins.VALID_HOOKS` and expects no selector registration when that live fallback lacks `select_tool_schemas`.
- Independent probe in this review confirmed both paths: explicit supported hook registers both hooks and returns `True`; explicit unsupported hook registers only `pre_llm_call` and returns `False`.
- Full pytest now passes in the same reviewer repo/venv command that failed in HGZ-16.

Conclusion: B5 was fixed by making the positive registration test declare its required hook surface explicitly. The repair does not hide or incorrectly bypass unsupported selector-hook behavior; the unavailable-hook path remains tested and fail-safe.

## B1-B4 repair status

B1-B4 remain substantively repaired. Since `0613989` changed only `tests/test_handlers_integration.py`, the B1-B4 source repairs reviewed in HGZ-16 were not altered by the B5 repair. I also spot-checked the relevant source surfaces and reran the targeted regression files.

### B1: progressive eligibility / disabled-tool enforcement

Status: remains repaired.

Evidence:

- `session_tools._schema_is_eligible()` checks schema type, disabled tools, disabled toolsets, MCP exclusion, and native exclusion (`session_tools.py:225-240`).
- `tool_slimmer_tool_search()` applies `_schema_is_eligible()` and marks ineligible tools `disabled: true` / `can_load: false` (`session_tools.py:335-372`).
- `tool_slimmer_tool_details(load=True)` rejects disabled or ambiguous tools before `state.add()` (`session_tools.py:422-472`).
- Targeted HGZ-14 regression suite exited 0 in this review.

### B2: session-scoped progressive state

Status: remains repaired for the HGZ-14 blocker scope.

Evidence:

- `select_tool_schemas_callback()` receives `session_id` and passes it into `_inject_session_loaded()` (`integration.py:156-165`, `integration.py:305`).
- `_inject_session_loaded()` constructs `SessionLoadedState(..., session_id=session_id)` and filters loaded names through `_schema_is_eligible()` before merging (`integration.py:331-362`).
- `SessionLoadedState` retains per-session state and metadata including last-used/use-count/toolset; targeted regression/session tests exited 0.

Caveat preserved from HGZ-16: missing session IDs share the explicit anonymous bucket. That is not treated as a blocker for this scoped re-review because the previous accepted repair defined and tested that behavior as the safe anonymous fallback.

### B3: embedding cache provenance

Status: remains repaired for the HGZ-14 blocker scope.

Evidence:

- `CacheProvenance` includes checksum, provider ID, model ID, dimension, and per-schema canonical text hashes, and derives the cache filename from that tuple (`embeddings.py:211-231`).
- `EmbeddingCache._validate_meta()` checks checksum, dimension, provider ID, model ID, and text hashes before cache hits (`embeddings.py:268-280`).
- `SemanticRanker.embed_documents()` builds full provenance and uses `cache.load(provenance)` / `cache.save(provenance, ...)` (`embeddings.py:438-460`).
- Targeted embeddings/regression tests exited 0.

Caveat preserved from HGZ-16: legacy checksum-only `EmbeddingCache.load/save` signatures remain for compatibility, but the repaired semantic-ranker path no longer uses them.

### B4: `semantic_hybrid` schema exposure / drift guard

Status: remains repaired.

Evidence:

- `SELECT_SCHEMA` exposes `semantic_hybrid` in the public `mode` enum (`schemas.py:7-16`).
- `VALID_MODES` includes `semantic_hybrid` (`config.py:13`).
- HGZ-14 regression tests include schema/config synchronization checks and exited 0.

## Hidden broker / external-action / non-authorization check

Status: no violation found.

Evidence:

- `tool_slimmer_tool_details()` returns schema/info and can only mutate session-loaded state through `state.add()` / unload state; it does not invoke arbitrary tools or execute hidden broker calls (`session_tools.py:390-479`).
- `__init__.py:28-35` registers named Tool Slimmer tools/commands and `maybe_register_selector_hook(ctx)`; it does not register a generic hidden-tool executor.
- Search of the current source for execution/broker primitives found no `subprocess`, `os.system`, `Popen`, `exec(`, or `eval(` in `src/hermes_tool_slimmer`. The only network call found is the explicit OpenAI-compatible embedding provider HTTP request in `embeddings.py`, which is part of the semantic embedding feature rather than a hidden-tool broker.
- Commands run during this review were local git, pytest, ruff, read/grep/search, and a local Python semantics probe. No push, upstream PR, public package publish, live default-profile install/enablement, gateway restart, provider credential change, destructive mutation of existing Tool Slimmer/Hermes installs, or generic hidden-tool broker execution was performed.

## Evidence audit summary

- Task / board: `t_ab4575dc` / `hermes-gizmo`.
- Claim scope: final independent re-review after HGZ-16 B5 repair, including B1-B4 regression spot-checks, B5 deterministic repair, full pytest/ruff evidence, clean worktree evidence, hidden-broker check, and non-authorization preservation on `janusz/hermes-gizmo` at reviewed implementation HEAD `0613989bfa8b4cfe4d0bfa70ce70475ac9e5325d`.
- Explicit non-claims: no deployment, publication, upstream submission, default-profile enablement, live mutation, generic hidden-tool execution, or final human approval authorized.
- Proof objects inspected: git branch/log/diff, `review/HGZ-14-implementation-review.md`, `review/HGZ-16-repair-rereview.md`, `tests/test_handlers_integration.py`, `src/hermes_tool_slimmer/integration.py`, `src/hermes_tool_slimmer/session_tools.py`, `src/hermes_tool_slimmer/embeddings.py`, `src/hermes_tool_slimmer/schemas.py`, `src/hermes_tool_slimmer/config.py`, local pytest/ruff output, and independent selector-hook probe output.
- Strongest evidence depth: local source inspection, local git evidence, local full-suite command evidence, targeted regression command evidence, independent deterministic semantics probe.
- MechanicalVerdict: PASS — repo, branch, commit list, repair diff, source, tests, and review artifact are inspectable.
- SubstantiveVerdict: SUPPORTED — B5 is repaired, B1-B4 remain substantively repaired in the unchanged relevant source, full pytest/ruff pass, and no hidden broker or non-authorized external action was found within the reviewed scope.
- Recommendation: ACCEPT_WITH_QUALIFICATIONS — safe to present to HG-02 for explicit final human decision only; do not overread this as approval to push, publish, install, restart, mutate credentials, or execute hidden tools.

## Final verdict

PASS
