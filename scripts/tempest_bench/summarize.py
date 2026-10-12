#!/usr/bin/env python3
"""Markdown tables for a tempest_bench run: per arm (pass, model calls, tokens, est. cost) and per task."""

from __future__ import annotations

import json
import sys
from collections import defaultdict

ARM_LABEL = {"legacy": "legacy (default app)", "tempest-f1": "Tempest Fase 1", "tempest-default": "Tempest Fase 2"}


def main() -> None:
    rows = []
    for line in open(sys.argv[1], encoding="utf-8"):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "crash" in d:
            print(f"<!-- crash: {d['task']} {d['arm']} {d['seed']} -->")
            continue
        rows.append(d)
    arms = [a for a in ARM_LABEL if any(r["arm"] == a for r in rows)]
    by = defaultdict(list)
    for r in rows:
        by[r["arm"]].append(r)
    print("| arm | pass | model calls (sum) | input tok | output tok | cache_read_ratio | est. cost USD |")
    print("|---|---|---|---|---|---|---|")
    for a in arms:
        rs = by[a]
        tin = sum(r["input_tokens"] for r in rs)
        print(f"| {ARM_LABEL[a]} | {sum(r['passed'] for r in rs)}/{len(rs)} | {sum(r['turns'] for r in rs)} | "
              f"{tin:,} | {sum(r['output_tokens'] for r in rs):,} | "
              f"{sum(r['cache_read'] for r in rs) / tin if tin else 0:.3f} | {sum(r['cost_usd'] for r in rs):.4f} |")
    print()
    tasks = list(dict.fromkeys(r["task"] for r in rows))
    print("| task | " + " | ".join(ARM_LABEL[a] for a in arms) + " |")
    print("|---|" + "---|" * len(arms))
    for t in tasks:
        cells = []
        for a in arms:
            rs = [r for r in rows if r["task"] == t and r["arm"] == a]
            if not rs:
                cells.append("-")
                continue
            calls = sum(r["turns"] for r in rs) / len(rs)
            tok = sum(r["input_tokens"] + r["output_tokens"] for r in rs) / len(rs)
            cells.append(f"{sum(r['passed'] for r in rs)}/{len(rs)} · {calls:.1f} calls · {tok / 1000:.1f}k tok")
        print(f"| {t} | " + " | ".join(cells) + " |")
    print()
    # cost on runs every arm passed (same task+seed): failures that stop early don't flatter anyone
    keyed = defaultdict(dict)
    for r in rows:
        keyed[(r["task"], r["seed"])][r["arm"]] = r
    both = [k for k, v in keyed.items() if all(a in v and v[a]["passed"] for a in arms)]
    if both and len(arms) > 1:
        print(f"Runs passed by every arm: {len(both)}. Totals on those runs only:")
        print()
        print("| arm | model calls | input tok | est. cost USD |")
        print("|---|---|---|---|")
        for a in arms:
            rs = [keyed[k][a] for k in both]
            print(f"| {ARM_LABEL[a]} | {sum(r['turns'] for r in rs)} | {sum(r['input_tokens'] for r in rs):,} | "
                  f"{sum(r['cost_usd'] for r in rs):.4f} |")


if __name__ == "__main__":
    main()
