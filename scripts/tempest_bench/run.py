#!/usr/bin/env python3
"""Tempest small bench: 12 deterministic coding/agentic tasks, legacy vs Tempest (Fase 1) vs Tempest (Fase 2).

Thin wrapper over core/bench/tempest_ab.py (the scripted-policy replay bench: real Agent loop,
real tools/pytest/git, only the model's choices are scripted). No network, no API key.

    python3 scripts/tempest_bench/run.py [OUT.jsonl] [--seeds 0,1,2] [--jobs 2]
    python3 scripts/tempest_bench/summarize.py OUT.jsonl > RESULTS.md

Re-running with the same OUT resumes (finished runs are kept).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AB = ROOT / "core" / "bench" / "tempest_ab.py"

TASKS = [
    # existing replay tasks, one or two per family
    "bugfix-careless",          # claims done after half a fix (verify gate)
    "bugfix-diligent",          # runs tests itself (control)
    "syntax-slip",              # broken write (syntax check + restore)
    "refactor-5-files",         # multi-file rename
    "defect-missing-import",    # seeded defect, held-out test (lint gate)
    "clean-preexisting-diag",   # false-reject control
    "rollback-bad-import",      # never fixed: repo must not be left broken
    "long-refactor-16-32k",     # long horizon on a 32K window (compaction)
    # Fase 2 tasks (core/bench/tempest_tasks_f2.py)
    "recall-port-2sessions",    # session_search across chats
    "memory-nudge-pref",        # memory reminder + dedup across chats
    "claim-no-tests",           # "done" without evidence in a folder without tests
    "skill-reuse-2sessions",    # skill offer after a verified task, reused in the next chat
]
ARMS = ["legacy", "tempest-f1", "tempest-default"]


def main() -> None:
    args = sys.argv[1:]
    out = args.pop(0) if args and not args[0].startswith("--") else str(ROOT / "core" / "bench" / "results-f2.jsonl")
    opts = {"--seeds": "0,1,2", "--jobs": "2"}
    for i in range(0, len(args) - 1, 2):
        opts[args[i]] = args[i + 1]
    env = dict(os.environ)
    env.setdefault("TEMPEST_BENCH_DIR", "/tmp/tempest-bench-f2")
    cmd = [sys.executable, str(AB), "all", out, "--arms", ",".join(ARMS), "--tasks", ",".join(TASKS),
           "--seeds", opts["--seeds"], "--jobs", opts["--jobs"]]
    raise SystemExit(subprocess.call(cmd, env=env))


if __name__ == "__main__":
    main()
