# tempest_bench

A small benchmark you can rerun: 12 deterministic coding/agentic tasks comparing the legacy harness, Tempest Fase 1 and Tempest Fase 2. It needs no network and no API key.

```bash
cd core && pip install -e . pytest tiktoken      # tiktoken optional (falls back to chars/4)
python3 ../scripts/tempest_bench/run.py ../scripts/tempest_bench/results-replay.jsonl --jobs 2
python3 ../scripts/tempest_bench/summarize.py ../scripts/tempest_bench/results-replay.jsonl
```

## How it works

- It wraps `core/bench/tempest_ab.py`, the scripted-policy replay bench. The real `Agent` loop, tools, pytest, git and harness all run; only the model's choices are scripted.
- Tokens are counted with tiktoken cl100k on the exact wire.
- Cost uses an assumed cheap-model price of $0.30/M input, $0.03/M cached and $1.20/M output. This is not a quote.
- The tasks cover 8 existing families plus 4 Fase 2 `learn` tasks (`core/bench/tempest_tasks_f2.py`). The policies of the `learn` tasks encode assumptions about model behaviour, which are written down in that file. Treat their pass rates as proof that the mechanisms work end to end, not as model measurements.

## Result (2026-10-12, 3 seeds, 108 runs, `results-replay.jsonl`)

| arm | pass | model calls (sum) | input tok | output tok | cache_read_ratio | est. cost USD |
|---|---|---|---|---|---|---|
| legacy (default app) | 21/36 | 435 | 4,675,862 | 13,770 | 0.757 | 0.4641 |
| Tempest Fase 1 | 27/36 | 402 | 4,780,858 | 14,559 | 0.857 | 0.3458 |
| Tempest Fase 2 | 36/36 | 414 | 4,969,399 | 15,678 | 0.854 | 0.3642 |

| task | legacy (default app) | Tempest Fase 1 | Tempest Fase 2 |
|---|---|---|---|
| bugfix-careless | 0/3 · 6.0 calls · 59.9k tok | 3/3 · 6.0 calls · 60.6k tok | 3/3 · 6.0 calls · 62.4k tok |
| bugfix-diligent | 3/3 · 7.0 calls · 65.9k tok | 3/3 · 5.0 calls · 45.4k tok | 3/3 · 5.0 calls · 46.8k tok |
| syntax-slip | 3/3 · 10.0 calls · 101.9k tok | 3/3 · 5.0 calls · 46.6k tok | 3/3 · 5.0 calls · 48.1k tok |
| refactor-5-files | 3/3 · 15.0 calls · 242.0k tok | 3/3 · 13.0 calls · 203.4k tok | 3/3 · 13.0 calls · 207.3k tok |
| defect-missing-import | 0/3 · 6.0 calls · 58.3k tok | 3/3 · 6.0 calls · 58.6k tok | 3/3 · 6.0 calls · 60.4k tok |
| clean-preexisting-diag | 3/3 · 6.0 calls · 46.0k tok | 3/3 · 4.0 calls · 30.3k tok | 3/3 · 4.0 calls · 31.5k tok |
| rollback-bad-import | 0/3 · 5.0 calls · 38.0k tok | 3/3 · 7.0 calls · 55.9k tok | 3/3 · 7.0 calls · 58.0k tok |
| long-refactor-16-32k | 3/3 · 37.0 calls · 517.4k tok | 3/3 · 51.0 calls · 797.5k tok | 3/3 · 51.0 calls · 802.9k tok |
| recall-port-2sessions | 0/3 · 6.0 calls · 45.0k tok | 0/3 · 4.0 calls · 29.8k tok | 3/3 · 5.0 calls · 39.0k tok |
| memory-nudge-pref | 0/3 · 11.0 calls · 84.2k tok | 0/3 · 7.0 calls · 53.6k tok | 3/3 · 9.0 calls · 72.9k tok |
| skill-reuse-2sessions | 3/3 · 27.0 calls · 230.4k tok | 3/3 · 23.0 calls · 193.5k tok | 3/3 · 20.0 calls · 173.3k tok |
| claim-no-tests | 3/3 · 9.0 calls · 74.1k tok | 0/3 · 3.0 calls · 23.3k tok | 3/3 · 7.0 calls · 59.0k tok |

Runs passed by every arm: 18. Totals on those runs only:

| arm | model calls | input tok | est. cost USD |
|---|---|---|---|
| legacy (default app) | 306 | 3,602,843 | 0.3654 |
| Tempest Fase 1 | 303 | 3,941,107 | 0.2689 |
| Tempest Fase 2 | 294 | 3,920,356 | 0.2743 |
