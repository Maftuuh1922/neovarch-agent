"""The A/B replay bench itself: registry shape, cache simulators, one real run."""

import json
import subprocess
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent / "bench"
sys.path.insert(0, str(BENCH))

import tempest_ab  # noqa: E402
import tempest_tasks  # noqa: E402


def test_registry_shape():
    tasks = tempest_tasks.TASKS
    assert 30 <= len(tasks) <= 60
    assert {t["split"] for t in tasks.values()} == {"dev", "heldout"}
    held = [n for n, t in tasks.items() if t["split"] == "heldout"]
    assert 6 <= len(held) <= len(tasks) // 3
    for name, t in tasks.items():
        assert len(t["seeds"]) >= 3, name
        assert t["prompts"] or t.get("sessions"), name
        assert t["check"] or t.get("check_all"), name
    for arm in tempest_ab.DEFAULT_ARMS:
        assert arm in tempest_ab.ARMS


def test_openai_cache_sim_counts_identical_prefix():
    sim = tempest_ab.CacheSim("openai")
    a = [("x" * 10, False)] * 30
    toks = [100] * 30
    assert sim.account(a, toks) == (0, 0)
    b = a[:20] + [("y", False)] * 15
    read, _ = sim.account(b, [100] * 35)
    assert read == 1920  # 2000 identical tokens, floored to 128-token steps


def test_anthropic_cache_sim_needs_breakpoints():
    sim = tempest_ab.CacheSim("anthropic")
    plain = [("s" * 10, False)] * 30
    assert sim.account(plain, [100] * 30) == (0, 0)
    assert sim.account(plain, [100] * 30) == (0, 0)  # no breakpoints, never cached
    sim = tempest_ab.CacheSim("anthropic")
    bp = [(f"c{i}", i in (9, 29)) for i in range(30)]
    read, write = sim.account(bp, [100] * 30)
    assert read == 0 and write == 3000
    nxt = bp[:29] + [("c29", False), ("new", True)]
    read, write = sim.account(nxt, [100] * 31)
    assert read == 3000 and write == 100  # lookback finds the old breakpoint one block back


def test_serialize_splits_content_parts():
    msgs = [{"role": "system", "content": [{"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}},
                                           {"type": "text", "text": "b"}]},
            {"role": "user", "content": "hi"}]
    chunks = tempest_ab.serialize([], msgs)
    assert [bp for _, bp in chunks] == [False, True, False, False]


def test_one_real_run(tmp_path):
    env = {"TEMPEST_BENCH_DIR": str(tmp_path), "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(BENCH / "tempest_ab.py"), "run", "json-config", "tempest-nomask", "1"],
                       capture_output=True, text=True, timeout=120, env=env)
    d = json.loads(r.stdout.strip().splitlines()[-1])
    assert d["passed"] and d["turns"] == 4 and 0 < d["cache_read_ratio"] < 1
