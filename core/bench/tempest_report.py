"""Tables for a tempest_ab.py results file (JSON lines).

    python3 bench/tempest_report.py RESULTS.jsonl [--baseline tempest-nomask] [--md]

Pass rate is per run; the 95% interval is a bootstrap over tasks (seeds of a task stay
together), 2000 resamples, fixed RNG seed. Paired deltas vs the baseline arm use the same
task bootstrap on per-task mean differences.
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict


def load(path: str) -> list[dict]:
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:  # a run killed mid-write; the resumable runner redoes it
            continue
    # newest record wins for a (task, arm, seed)
    last = {}
    for r in out:
        last[(r["task"], r["arm"], r.get("seed", 0))] = r
    return list(last.values())


def boot(per_task: dict[str, float], n: int = 2000, seed: int = 7) -> tuple[float, float]:
    keys = sorted(per_task)
    if not keys:
        return (0.0, 0.0)
    rnd = random.Random(seed)
    vals = []
    for _ in range(n):
        s = [per_task[rnd.choice(keys)] for _ in keys]
        vals.append(sum(s) / len(s))
    vals.sort()
    return vals[int(0.025 * n)], vals[int(0.975 * n) - 1]


def summarize(rows: list[dict], arms: list[str], split: str | None = None) -> list[dict]:
    out = []
    for arm in arms:
        rs = [r for r in rows if r["arm"] == arm and (split is None or r.get("split") == split)]
        ok = [r for r in rs if "crash" not in r]
        if not rs:
            continue
        per_task = defaultdict(list)
        for r in ok:
            per_task[r["task"]].append(1.0 if r["passed"] else 0.0)
        pt = {k: sum(v) / len(v) for k, v in per_task.items()}
        lo, hi = boot(pt)
        tin = sum(r["input_tokens"] for r in ok)
        tread = sum(r["cache_read"] for r in ok)
        out.append({
            "arm": arm, "runs": len(rs), "crashes": len(rs) - len(ok),
            "pass": sum(r["passed"] for r in ok), "pass_rate": sum(r["passed"] for r in ok) / max(len(ok), 1),
            "ci": (lo, hi), "input": tin, "uncached": tin - tread,
            "cache_read_ratio": tread / tin if tin else 0.0,
            "cost": sum(r["cost_usd"] for r in ok), "output": sum(r["output_tokens"] for r in ok),
            "prefix_breaks": sum(r.get("prefix_breaks", 0) for r in ok),
            "overflow": sum(1 for r in ok if r.get("overflow")),
            "false_reject": sum(1 for r in ok if r.get("false_reject")),
            "turns": sum(r["turns"] for r in ok),
        })
    return out


def paired(rows: list[dict], arm: str, base: str, key: str) -> tuple[float, float, float]:
    a, b = defaultdict(list), defaultdict(list)
    for r in rows:
        if "crash" in r:
            continue
        v = (1.0 if r["passed"] else 0.0) if key == "pass" else float(r[key])
        if r["arm"] == arm:
            a[r["task"]].append(v)
        elif r["arm"] == base:
            b[r["task"]].append(v)
    diffs = {t: sum(a[t]) / len(a[t]) - sum(b[t]) / len(b[t]) for t in a if t in b}
    if not diffs:
        return 0.0, 0.0, 0.0
    lo, hi = boot(diffs)
    return sum(diffs.values()) / len(diffs), lo, hi


def table(summary: list[dict]) -> str:
    head = ("| arm | runs | pass | pass rate (95% CI) | input tok | uncached tok | cache_read_ratio | est. cost USD "
            "| prefix breaks | overflow | false reject |\n|---|---|---|---|---|---|---|---|---|---|---|")
    lines = [head]
    for s in summary:
        lines.append(f"| {s['arm']} | {s['runs']}{' (' + str(s['crashes']) + ' crash)' if s['crashes'] else ''} "
                     f"| {s['pass']} | {100 * s['pass_rate']:.1f}% ({100 * s['ci'][0]:.0f}–{100 * s['ci'][1]:.0f}) "
                     f"| {s['input']:,} | {s['uncached']:,} | {s['cache_read_ratio']:.3f} | {s['cost']:.4f} "
                     f"| {s['prefix_breaks']} | {s['overflow']} | {s['false_reject']} |")
    return "\n".join(lines)


def family_table(rows: list[dict], arms: list[str]) -> str:
    fams = sorted({r.get("family", "?") for r in rows})
    lines = ["| family | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    for f in fams:
        cells = []
        for a in arms:
            rs = [r for r in rows if r["arm"] == a and r.get("family") == f and "crash" not in r]
            cells.append(f"{sum(r['passed'] for r in rs)}/{len(rs)}" if rs else "–")
        lines.append(f"| {f} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    path = sys.argv[1]
    base = "tempest-nomask"
    if "--baseline" in sys.argv:
        base = sys.argv[sys.argv.index("--baseline") + 1]
    rows = load(path)
    arms = []
    for r in rows:
        if r["arm"] not in arms:
            arms.append(r["arm"])
    print("## All tasks\n")
    print(table(summarize(rows, arms)))
    for split in ("dev", "heldout"):
        print(f"\n## Split: {split}\n")
        print(table(summarize(rows, arms, split)))
    print("\n## Pass by family\n")
    print(family_table(rows, arms))
    if any(r["arm"] == base for r in rows):
        print(f"\n## Cost on runs that both the arm and {base} passed (same task+seed)\n")
        print("| arm | common runs | input tok (arm vs base) | Δ input | est. cost USD (arm vs base) | Δ cost "
              "| cache_read_ratio (arm vs base) |\n|---|---|---|---|---|---|---|")
        idx = {(r["task"], r.get("seed", 0), r["arm"]): r for r in rows if "crash" not in r}
        for a in arms:
            if a == base:
                continue
            n = ia = ib = ra = rb = 0
            ca = cb = 0.0
            for (t, s_, ar), r in idx.items():
                o = idx.get((t, s_, a))
                if ar != base or not o or not (o["passed"] and r["passed"]):
                    continue
                n += 1
                ia, ib = ia + o["input_tokens"], ib + r["input_tokens"]
                ca, cb = ca + o["cost_usd"], cb + r["cost_usd"]
                ra, rb = ra + o["cache_read"], rb + r["cache_read"]
            if n and ib and cb:
                print(f"| {a} | {n} | {ia:,} vs {ib:,} | {100 * (ia - ib) / ib:+.1f}% | {ca:.4f} vs {cb:.4f} "
                      f"| {100 * (ca - cb) / cb:+.1f}% | {ra / ia:.3f} vs {rb / ib:.3f} |")
        print(f"\n## Paired deltas vs {base} (per-task mean, 95% bootstrap CI over tasks)\n")
        print("| arm | Δ pass rate | Δ input tok/run | Δ cost USD/run |\n|---|---|---|---|")
        for a in arms:
            if a == base:
                continue
            p = paired(rows, a, base, "pass")
            i = paired(rows, a, base, "input_tokens")
            c = paired(rows, a, base, "cost_usd")
            print(f"| {a} | {100 * p[0]:+.1f} pt ({100 * p[1]:+.0f}…{100 * p[2]:+.0f}) | {i[0]:+,.0f} "
                  f"({i[1]:+,.0f}…{i[2]:+,.0f}) | {c[0]:+.5f} ({c[1]:+.5f}…{c[2]:+.5f}) |")


if __name__ == "__main__":
    main()
