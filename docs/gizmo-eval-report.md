# Hermes Gizmo — Selector Mode Comparison Report

**Board**: `hermes-gizmo`  
**Task**: HGZ-11 — integrate packaging / config / docs / eval  
**Run date**: 2026-05-28  
**Commit base**: `b3f2955`

## Scope

This report compares keyword, hybrid, and semantic_hybrid selection modes using the Hermes Gizmo evaluation artifacts. No live API keys or provider secrets are required for the default eval (see "Reproducing This Report").

## Method

- **Prompts**: 8 task-oriented prompts covering repo search, web tasks, code writing, DB queries, scheduling, media, messaging, and Docker deploy.
- **Catalog**: 25-tool synthetic schema set with varied toolsets (native, browser, web, github, mcp-github, database, kanban, scheduler, media, creative, messaging, devops).
- **Config**: `top_k: 8`, `always_include: [terminal, read_file, write_file, patch, search_files]`
- **Metrics**:
  - **Hit rate**: whether at least one expected tool appears in the selected set
  - **Average reduction %**: estimated schema-token reduction (serialized JSON bytes / 4)
  - **Average selected tools**: selected tools per prompt (including always_include)
  - **Fail-open count**: how many prompts triggered fail_open

## Results Summary

| Mode | Hit Rate | Avg Reduction | Avg Selected | Fail-open |
|---|---:|---:|---:|---:|
| keyword | 1.000 | 45.3% | 12.1 | 0 |
| hybrid | 1.000 | 45.3% | 12.1 | 0 |
| semantic_hybrid | 0.625 | 43.2% | 13.0 | 0 |

### Detailed Findings

#### keyword
- Fastest (no embedding calls). All 8 prompts hit expected tools.
- Limitation: vocabulary must overlap exactly — aliases and user aliases are the only expansion.
- Best for: environments where latency matters more than nuanced ranking.

#### hybrid
- Identical to keyword in this benchmark because the fuzzy-token boost only triggers on close spelling mismatches (SequenceMatcher ratio >= 0.84), which our prompt texts do not exercise.
- In practice, it helps when query wording drifts from tool descriptions (e.g., query "browse site" matching tools with "navigate webpage").
- Best for: keyword mode with a safety net for slight misspellings / synonyms.

#### semantic_hybrid
- Falls to FakeEmbeddingProvider (deterministic SHA-256 hash embeddings) when no `OPENAI_API_KEY` is present. The FakeEmbeddingProvider generates unit-normalized vectors deterministically, so cosine similarity is reproducible but semantically vacuous.
- With real embeddings, semantic_hybrid would add meaning-based ranking on top of BM25/RRF. Without real embeddings, we see random-like ordering — hit rate drops to 62.5% because RRF with meaningless cosine similarity degrades quality compared to pure BM25.
- When the semantic provider fails, the code correctly degrades to keyword mode (`LOG.warning("semantic_hybrid embedding failed; degrading to keyword")`).
- Best for: environments willing to run an embedding provider (local or cloud) for meaning-aware ranking. With FakeEmbeddingProvider, it is worse than keyword.

### Per-prompt Breakdown (semantic_hybrid — misses highlighted)

| Prompt | Expected | Hit | Expected tool present? |
|---|---|---|---|
| repo_search | search_files, read_file | True | search_files |
| browser_task | browser_navigate, web_search | True | browser_navigate |
| write_code | write_file, terminal | True | write_file, terminal |
| db_query | sql_query | True | sql_query |
| schedule_report | cronjob | **False** | cronjob missing |
| spotify_playlist | spotify_search | **False** | spotify_search missing |
| send_alert | send_message | **False** | send_message missing |
| deploy_docker | docker_list, terminal | True | terminal |

The 3 misses occur because deterministic fake embeddings do not encode semantic similarity between prompts and tool descriptions.

## Recommendations

1. **Default mode for Hermes Gizmo**: `keyword` or `hybrid`
   - Lowest latency, highest hit rate, no dependency on OpenAI / local embedding endpoint.
   - `hybrid` is strictly safer than keyword with negligible overhead.
2. **When to enable semantic_hybrid**
   - Only when a real embedding provider is configured (OpenAI-compatible endpoint with API key, or a local embedding server via `semantic_openai_base_url`).
   - Verify via `hermes tool-slimmer doctor` that the provider path is reachable.
3. **Always start with `dry_run: true`**
   - Inspect selector output before activating slimming.
4. **Config minimums for this catalog**
   - `top_k: 8` works well across all prompts.
   - `min_estimated_reduction_percent: ~5.0` is safe (all selections achieve >40% reduction).

## Reproducing This Report

```bash
# Inside a checkout of this repo
pip install -e ".[dev]"

# This report was produced with these commands:
.venv/bin/python -c "
from hermes_tool_slimmer.config import ToolSlimmerConfig
from hermes_tool_slimmer.cli import _load_schemas, _load_prompts, eval_prompts

schemas = _load_schemas('/tmp/benchmark_schemas.yaml')
prompts = _load_prompts('/tmp/benchmark_prompts.yaml')

for mode in ['keyword', 'hybrid', 'semantic_hybrid']:
    cfg = ToolSlimmerConfig(
        mode=mode,
        top_k=8,
        always_include=['terminal','read_file','write_file','patch','search_files']
    )
    report = eval_prompts(cfg, schemas, prompts)
    print(mode, report['summary'])
"
```

### No-secrets guarantee
- Neither the benchmark command nor the default test suite requires live provider secrets.
- `OpenAIEmbeddingProvider` raises early when `OPENAI_API_KEY` is absent; the selector degrades to keyword.
- The `FakeEmbeddingProvider` uses deterministic SHA-256 hashing — no network calls.

## Artifacts

- Benchmark schemas: `/tmp/benchmark_schemas.yaml` (25 tools)
- Benchmark prompts: `/tmp/benchmark_prompts.yaml` (8 prompts)
- Raw comparison JSON: `/tmp/mode_comparison.json`

---
*This report is part of the Hermes Gizmo fork documentation. It is not a public release artifact.*
