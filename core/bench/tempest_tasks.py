"""Scripted tasks for the deterministic Tempest A/B replay bench (bench/tempest_ab.py).

A task = fixture (builds the project for a seed) + scripted policy (plays the model: it only
reacts to what the harness shows it on the wire) + prompts/sessions + a check on the result.
Policies never peek at the files directly; anything they "know" came through the wire, or is
the scripted intent of the model (the edit it wants to make).

Families (``family`` key) and what they exercise:

* ``v1``         the original 9 Phase-1 tasks (seed 0 reproduces the old fixtures)
* ``bugfix``     careless fixes (claims done after half a fix) and diligent ones (runs tests itself)
* ``defect``     seeded defects that pass visible tests but fail held-out checks, plus clean
                 changes in files with pre-existing diagnostics (gate false-reject control)
* ``long``       long horizons on a small (32K) window: forces compaction / overflows raw context
* ``rollback``   changes that break a previously green repo and are never fixed (+ a good control)
* ``session``    work cut across sessions (forced resets) - progress artefacts
* ``chat``       multi-turn chats with a moving clock and mid-session config changes

``split``: "dev" tasks may be looked at when choosing defaults; "heldout" tasks are only
reported, never used to pick a default.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import textwrap
from pathlib import Path

SENTINEL = "\x00FILLER\x00"
MASKED_PREFIX = "[output alat lama"
VERIFY_MARK = "[verifikasi otomatis gagal"
LINT_MARK = "[pemeriksaan statis"
PLAN_MARK = "# Rencana & progres"


# ------------------------------------------------------------- helpers -----

def w(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    head, _sep, rest = text.partition(SENTINEL)
    p.write_text(textwrap.dedent(head).lstrip("\n") + rest, encoding="utf-8")


def filler(name: str, n: int, seed: int) -> str:
    """Realistic-looking padding functions so files have real size."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        a, b = rnd.choice(["items", "rows", "records", "values"]), rnd.choice(["limit", "offset", "size", "step"])
        out.append(f'''
def {name}_helper_{i}({a}, {b}=10):
    """Return a filtered slice of {a} for page handling ({i})."""
    result = []
    for idx, item in enumerate({a}):
        if idx % {b} == {i % 7} and item is not None:
            result.append(item)
        elif isinstance(item, dict) and item.get("keep"):
            result.append(dict(item, page={i}))
    return result[:{b} * {rnd.randint(2, 9)}]
''')
    return SENTINEL + "".join(out)


TEST_HEAD = "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"


class P:
    """Tool-call factory for scripted policies (ids c1, c2, ... per run)."""

    def __init__(self):
        self.n = 0

    def call(self, name: str, **args):
        from neovarch.llm import ToolCall
        self.n += 1
        return ToolCall(id=f"c{self.n}", name=name, arguments=json.dumps(args, ensure_ascii=False))


def last_tool_outputs(wire) -> list[str]:
    out = []
    for m in reversed(wire):
        if m["role"] == "tool":
            out.append(_text(m))
        else:
            break
    return list(reversed(out))


def _text(m) -> str:
    c = m.get("content")
    if isinstance(c, list):
        return "".join(str(p.get("text") or "") for p in c if isinstance(p, dict))
    return str(c or "")


def last_text(wire) -> str:
    return _text(wire[-1]) if wire else ""


def feedback(wire) -> str | None:
    """'verify' / 'lint' when the harness just pushed back on a finish, else None."""
    if not wire or wire[-1]["role"] != "user":
        return None
    t = _text(wire[-1])
    if t.startswith(VERIFY_MARK) or VERIFY_MARK in t[:200]:
        return "verify"
    if t.startswith(LINT_MARK) or LINT_MARK in t[:200]:
        return "lint"
    return None


def visible(wire, call_id: str) -> bool:
    for m in wire:
        if m["role"] == "tool" and m.get("tool_call_id") == call_id:
            return not _text(m).startswith(MASKED_PREFIX)
    return False


def anywhere(wire, needle: str) -> bool:
    return any(needle in _text(m) for m in wire)


def plan_text(wire) -> str:
    """The newest progress recitation the harness put on the wire ('' if none)."""
    for m in reversed(wire):
        t = _text(m)
        i = t.rfind(PLAN_MARK)
        if i >= 0:
            return t[i:]
    return ""


def has_tool(st, name: str) -> bool:
    return name in st.get("_tools", ())


def pytest_ok(root: Path, extra: str | None = None) -> bool:
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if extra:
        args.append(extra)
    r = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=120)
    return r.returncode == 0


def heldout_ok(root: Path, test_src: str) -> bool:
    """Run a hidden test (not in the repo while the agent worked) against the result."""
    hid = root / "tests" / "test_zz_heldout.py"
    hid.parent.mkdir(exist_ok=True)
    hid.write_text(TEST_HEAD + textwrap.dedent(test_src), encoding="utf-8")
    try:
        return pytest_ok(root)
    finally:
        hid.unlink(missing_ok=True)


PYTEST = "python3 -m pytest -q -p no:cacheprovider"


# =================================================================== v1 =====
# The original nine tasks. Seed 0 reproduces the Phase-1 fixtures byte for byte.

def fx_bugfix_careless(root: Path, seed: int = 0) -> None:
    w(root, "stats.py", '''
        """Small statistics helpers."""


        def mean(xs):
            if not xs:
                raise ValueError("empty")
            return sum(xs) / (len(xs) - 1)


        def variance(xs):
            m = mean(xs)
            return sum((x - m) ** 2 for x in xs) / len(xs)


        def median(xs):
            s = sorted(xs)
            n = len(s)
            return s[n // 2]


        def mode(xs):
            counts = {}
            for x in xs:
                counts[x] = counts.get(x, 0) + 1
            return max(counts, key=lambda k: (counts[k], -k))
        ''' + filler("stats", 12 + 3 * seed, 1 + 100 * seed))
    w(root, "tests/test_stats.py", '''
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from stats import mean, variance, median, mode


        def test_mean():
            assert mean([1, 2, 3, 4]) == 2.5

        def test_variance():
            assert variance([2, 4, 4, 4, 5, 5, 7, 9]) == 4

        def test_median_odd():
            assert median([3, 1, 2]) == 2

        def test_median_even():
            assert median([4, 1, 3, 2]) == 2.5

        def test_mode():
            assert mode([1, 2, 2, 3]) == 2
        ''')


def pol_bugfix_careless(st, wire, p, root):
    ph = st.setdefault("ph", 0)
    fb = feedback(wire)
    if fb == "verify":
        st["ph"] = 10
        st["median"] = True
        return ("Refleksi: saya hanya memperbaiki mean; test_median_even gagal karena median tidak merata-ratakan "
                "dua nilai tengah untuk panjang genap. Coba beda: perbaiki median.",
                [p.call("edit_file", path="stats.py", old_text="    return s[n // 2]\n",
                        new_text="    if n % 2 == 0:\n        return (s[n // 2 - 1] + s[n // 2]) / 2\n    return s[n // 2]\n")])
    st["ph"] += 1
    if ph == 0:
        return "", [p.call("read_file", path="stats.py")]
    if ph == 1:
        return "", [p.call("read_file", path="tests/test_stats.py")]
    if ph == 2:
        return "Pembagi mean salah.", [p.call("edit_file", path="stats.py", old_text="sum(xs) / (len(xs) - 1)",
                                                  new_text="sum(xs) / len(xs)")]
    if st.get("median"):
        return "Sudah: mean membagi dengan len(xs) dan median merata-ratakan dua nilai tengah.", []
    return "Sudah saya perbaiki: mean sekarang membagi dengan len(xs).", []


def fx_bugfix_diligent(root: Path, seed: int = 0) -> None:
    w(root, "textutil.py", '''
        import re


        def slugify(text):
            text = re.sub(r"[^A-Za-z0-9]+", "-", text.strip())
            return text.strip("-")


        def truncate(text, n):
            return text if len(text) <= n else text[: n - 1] + "…"
        ''' + filler("text", 10 + 3 * seed, 2 + 100 * seed))
    w(root, "tests/test_textutil.py", '''
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from textutil import slugify, truncate

        def test_slugify():
            assert slugify("  Hello World!  ") == "hello-world"

        def test_slugify_numbers():
            assert slugify("Rilis 1.4.6") == "rilis-1-4-6"

        def test_truncate():
            assert truncate("abcdef", 4) == "abc…"
        ''')


def pol_bugfix_diligent(st, wire, p, root):
    ph = st.setdefault("ph", 0)
    st["ph"] += 1
    if ph == 0:
        return "", [p.call("shell", command=PYTEST)]
    if ph == 1:
        return "", [p.call("read_file", path="textutil.py")]
    if ph == 2:
        return "", [p.call("edit_file", path="textutil.py", old_text='    return text.strip("-")',
                           new_text='    return text.strip("-").lower()')]
    if ph == 3:
        return "", [p.call("shell", command=PYTEST)]
    return "slugify sekarang menurunkan huruf; semua tes lulus.", []


def fx_syntax_slip(root: Path, seed: int = 0) -> None:
    w(root, "inventory.py", '''
        MAX_STOCK = 100


        def restock(qty, n):
            if n < 0:
                raise ValueError("n must be >= 0")
            return qty + n


        def sell(qty, n):
            if n > qty:
                raise ValueError("not enough stock")
            return qty - n
        ''' + filler("inv", 10 + 3 * seed, 3 + 100 * seed))
    w(root, "tests/test_inventory.py", '''
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import pytest
        from inventory import restock, sell

        def test_restock_caps():
            assert restock(95, 10) == 100

        def test_restock():
            assert restock(1, 2) == 3

        def test_sell():
            assert sell(5, 2) == 3
            with pytest.raises(ValueError):
                sell(1, 2)
        ''')


BAD = "    total = qty + n\n      return min(total, MAX_STOCK)\n"
GOOD = "    total = qty + n\n    return min(total, MAX_STOCK)\n"


def pol_syntax_slip(st, wire, p, root):
    outs = last_tool_outputs(wire)
    last = outs[-1] if outs else ""
    if last.startswith("rejected:"):
        return "Indentasi salah, kirim ulang.", [p.call("edit_file", path="inventory.py", old_text="    return qty + n\n",
                                                         new_text=GOOD)]
    if ("IndentationError" in last or "SyntaxError" in last) and not st.get("fixed"):
        st["fixed"] = True
        return "Ada IndentationError, saya betulkan.", [p.call("edit_file", path="inventory.py", old_text=BAD, new_text=GOOD)]
    ph = st.setdefault("ph", 0)
    st["ph"] += 1
    if ph == 0:
        return "", [p.call("read_file", path="inventory.py")]
    if ph == 1:
        return "", [p.call("edit_file", path="inventory.py", old_text="    return qty + n\n", new_text=BAD)]
    if "passed" in last and "failed" not in last and "error" not in last.lower():
        return "restock sekarang dibatasi MAX_STOCK; tes lulus.", []
    if ph > 8:
        return "Belum berhasil.", []
    return "", [p.call("shell", command="python3 -m pytest -p no:cacheprovider")]


LOG_LINES = 20000


def fx_big_log(root: Path, seed: int = 0, lines_n: int = LOG_LINES) -> None:
    rnd = random.Random(42 + seed)
    lines = []
    services = ["api", "worker", "relay", "sync", "auth"]
    for i in range(lines_n):
        h = 8 + (i * 6) // lines_n
        m, s = (i * 7) % 60, (i * 13) % 60
        lvl = rnd.choices(["INFO", "DEBUG", "WARN", "ERROR"], [70, 18, 8, 4])[0]
        if lvl == "ERROR":
            msg = rnd.choice(["db-timeout after 5000ms", "upstream 502", "token expired", "db-timeout after 3000ms"])
        else:
            msg = rnd.choice(["request ok", "cache hit", "cache miss", "retrying", "queue depth 3", "gc pause 12ms"])
        lines.append(f"2026-10-11T{h:02d}:{m:02d}:{s:02d}Z {lvl:<5} {rnd.choice(services):<6} "
                     f"req=r{i:06d} {msg}")
    (root / "app.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def big_log_truth(root: Path) -> tuple[int, str]:
    hits = [l for l in (root / "app.log").read_text().splitlines() if "T10:" in l and " ERROR " in l and "db-timeout" in l]
    return len(hits), hits[0].split("req=")[1].split()[0]


def pol_big_log(st, wire, p, root):
    ph = st.setdefault("ph", 0)
    st["ph"] += 1
    if ph == 0:
        return "", [p.call("shell", command="cat app.log")]
    if ph == 1:
        return "", [p.call("shell", command="grep 'T10:' app.log | grep -cE 'ERROR .*db-timeout'")]
    if ph == 2:
        st["count"] = last_tool_outputs(wire)[-1].splitlines()[-1].strip()
        return "", [p.call("shell", command="grep 'T10:' app.log | grep -m1 -E 'ERROR .*db-timeout'")]
    first = last_tool_outputs(wire)[-1].split("req=")[1].split()[0]
    return f"Ada {st['count']} kejadian ERROR db-timeout antara 10:00–10:59; request pertama {first}.", []


def chk_big_log(root, final):
    n, rid = big_log_truth(root)
    return f"Ada {n} " in final and rid in final


MODS5 = ["views", "api", "reports"]
MODS10 = ["views", "api", "reports", "admin", "billing", "emails", "search", "export"]
MODS16 = MODS10 + ["audit", "cache", "queue", "media", "auth", "jobs"]


def refactor_files(mods: list[str]) -> list[str]:
    return ["app/users.py"] + [f"app/{m}.py" for m in mods] + ["tests/test_app.py"]


def fx_refactor(root: Path, mods: list[str] = MODS5, seed: int = 0, size: int = 14) -> None:
    w(root, "app/__init__.py", "")
    w(root, "app/users.py", '''
        USERS = {1: {"first": "Ayu", "last": "Lestari"}, 2: {"first": "Raka", "last": "Pratama"}}


        def get_user_name(uid):
            u = USERS[uid]
            return f"{u['first']} {u['last']}"
        ''' + filler("users", size + 2 * seed, 4 + 100 * seed))
    for i, mod in enumerate(mods):
        w(root, f"app/{mod}.py", f'''
            from app.users import get_user_name


            def {mod}_title(uid):
                return "[{mod}] " + get_user_name(uid)
            ''' + filler(mod, size + 2 * seed, 10 + i + 100 * seed))
    w(root, "tests/test_app.py", '''
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from app import users, views, api, reports
        import app as _pkg

        def test_renamed():
            assert not hasattr(users, "get_user" + "_name")
            assert users.fetch_display_name(1) == "Ayu Lestari"

        def test_callers():
            assert views.views_title(2) == "[views] Raka Pratama"
            assert api.api_title(1) == "[api] Ayu Lestari"
            assert reports.reports_title(2) == "[reports] Raka Pratama"
        ''' + filler("tst", 6, 9 + 100 * seed))
    if len(mods) > 3:
        with (root / "tests/test_app.py").open("a") as fh:
            fh.write("\n\ndef test_more():\n    import importlib\n    for m in %r:\n"
                     "        mod = importlib.import_module('app.' + m)\n"
                     "        assert getattr(mod, m + '_title')(1).endswith('Ayu Lestari')\n" % (mods[3:],))


def pol_refactor(st, wire, p, root, files=None):
    files = files or refactor_files(MODS5)
    ph = st.setdefault("ph", 0)
    reads = st.setdefault("reads", {})
    edits = st.setdefault("edits", 0)
    if ph == 0:
        st["ph"] = 1
        return "", [p.call("shell", command="grep -rln get_user_name .")]
    if ph == 1:
        f = files[len(reads)]
        c = p.call("read_file", path=f)
        reads[f] = c.id
        if len(reads) == len(files):
            st["ph"] = 2
        return "", [c]
    if ph == 2:
        if edits < len(files):
            f = files[edits]
            if not visible(wire, reads[f]):  # masked/compacted away: a real model must look again
                st["rereads"] = st.get("rereads", 0) + 1
                c = p.call("read_file", path=f)
                reads[f] = c.id
                return f"Isi {f} sudah tidak terlihat, baca ulang.", [c]
            st["edits"] = edits + 1
            return "", [p.call("edit_file", path=f, old_text="get_user_name", new_text="fetch_display_name",
                               replace_all=True)]
        st["ph"] = 3
        return "", [p.call("shell", command=PYTEST)]
    return f"get_user_name diganti fetch_display_name di {len(files)} file; tes lulus.", []


LONG_DIRS = ["core", "util", "net"]


def fx_long_session(root: Path, seed: int = 0, per_dir: int = 8, big: int = 0) -> None:
    rnd = random.Random(7 + seed)
    for d in LONG_DIRS:
        for j in range(per_dir):
            todos = "".join(f"\n# TODO({d}-{j}-{k}): handle edge case {k}\n" for k in range(rnd.randint(0, 3)))
            imp = "import requests\n" if rnd.random() < 0.3 else "import json\n"
            w(root, f"{d}/mod{j}.py", imp + todos + filler(f"{d}{j}", rnd.randint(4, 12) + big, 100 + j + 1000 * seed))
    w(root, "requirements.txt", "requests==2.32.3\npyyaml==6.0.2\n")


def long_truth(root: Path) -> dict:
    todo = {d: sum(p.read_text().count("# TODO(") for p in (root / d).glob("*.py")) for d in LONG_DIRS}
    sizes = {f"{d}/{p.name}": len(p.read_text().splitlines()) for d in LONG_DIRS for p in (root / d).glob("*.py")}
    req = sorted(f"{d}/{p.name}" for d in LONG_DIRS for p in (root / d).glob("*.py") if "import requests" in p.read_text())
    return {"todo": todo, "largest": max(sizes, key=lambda k: (sizes[k], k)), "requests": req}


def long_plan(per_dir: int = 8, reads: int = 8, asts: int = 4):
    plan = [("ls", "ls -R")]
    plan += [("todo:" + d, f"grep -n 'TODO' {d}/*.py") for d in LONG_DIRS]
    plan += [("wc", "wc -l " + " ".join(f"{d}/*.py" for d in LONG_DIRS))]
    plan += [("read", f"{d}/mod{j}.py") for d in LONG_DIRS for j in (0, 3, 5)][:reads]
    plan += [("req", "grep -rln 'import requests' " + " ".join(LONG_DIRS))]
    idx = [j for j in (1, 2, 4, 6, 7, 9) if j < per_dir][:asts]
    plan += [("ast", f"python3 -c \"import ast,sys;t=ast.parse(open('{d}/mod{j}.py').read());"
                     f"print([(n.name,n.lineno,len(ast.dump(n))) for n in t.body if isinstance(n,ast.FunctionDef)])\"")
             for d in LONG_DIRS for j in idx]
    plan += [("cat", "cat requirements.txt")]
    return plan


def pol_long_session(st, wire, p, root, plan_fn=long_plan):
    plan = st.setdefault("plan", plan_fn())
    i = st.setdefault("i", 0)
    note = ""
    if i > 0:
        kind = plan[i - 1][0]
        outs = last_tool_outputs(wire)
        out = outs[-1] if outs else ""
        if kind.startswith("todo:"):
            n = out.count("# TODO(")
            st.setdefault("todo", {})[kind[5:]] = n
            note = f"Catatan: {kind[5:]} punya {n} TODO."
        elif kind == "wc":
            rows = [l.split() for l in out.splitlines() if l.strip().endswith(".py")]
            best = max(rows, key=lambda r: (int(r[0]), r[1]))
            st["largest"] = best[1]
            note = f"Catatan: modul terbesar {best[1]} ({best[0]} baris)."
        elif kind == "req":
            st["requests"] = sorted(l.strip() for l in out.splitlines() if l.strip().endswith(".py"))
            note = "Catatan: yang import requests: " + ", ".join(st["requests"])
    if i >= len(plan):
        t = st["todo"]
        return (f"Audit selesai. TODO: core={t['core']}, util={t['util']}, net={t['net']}. "
                f"Modul terbesar: {st['largest']}. Import requests: {', '.join(st['requests'])}."), []
    st["i"] = i + 1
    kind, arg = plan[i]
    if kind == "read":
        return note, [p.call("read_file", path=arg)]
    return note, [p.call("shell", command=arg)]


def chk_long(root, final):
    t = long_truth(root)
    return (all(f"{d}={t['todo'][d]}" in final for d in LONG_DIRS) and t["largest"] in final
            and all(r in final for r in t["requests"]))


def fx_chat_vault(root: Path, seed: int = 0) -> None:
    w(root, "CHANGELOG.md", "# Changelog\n\n## 1.4.6 (belum rilis)\n- Mode ringan di HP\n- Relay baru\n" +
      "".join(f"\n## 1.4.{i}\n- perbaikan kecil {i}\n- peningkatan UI {i}\n" for i in range(5 + seed, 0, -1)))
    vault = root.parent / (root.name + "-vault")
    topics = {"rilis-1.4.6": "Rencana rilis 1.4.6: gabung ppt-master, relay, skill baru. Rilis barengan.",
              "meeting-relay": "Meeting relay: endpoint baru, retry eksponensial, uji di jaringan HP lambat.",
              "android-build": "Build APK: gradle cache, flutter 3.x, tanda tangan rilis.",
              "ide-kantor": "Ide Kantor 3D: taman, pegawai, status kerja.",
              "harness": "Catatan harness: masking, offload, verify gate, cache prefix.",
              "desktop-fix": "Perbaikan desktop: tsc error, preload, jendela.",
              "skills": "Skill: SKILL.md, katalog, auto-save draft.",
              "keuangan": "Biaya model: MiMo murah, 9Router gratis dengan batas."}
    for k, v in topics.items():
        w(vault, f"{k}.md", f"# {k}\n\n{v}\n\n" + (f"Detail {k}: " + "lorem ipsum dolor sit amet " * (40 + 10 * seed)) + "\n")


def pol_chat_vault(st, wire, p, root):
    user_turns = sum(1 for m in wire if m["role"] == "user")
    if user_turns == 2 and wire[-1]["role"] == "user":
        return "", [p.call("read_file", path="CHANGELOG.md")]
    if user_turns == 1:
        return "Rencana 1.4.6: ppt-master, relay dan skill baru dirilis bersamaan.", []
    if user_turns == 2:
        return "CHANGELOG 1.4.6 berisi Mode ringan di HP dan relay baru.", []
    return "Meeting relay: endpoint baru, retry eksponensial, diuji di jaringan HP lambat.", []


def fx_json_config(root: Path, seed: int = 0) -> None:
    hosts = ["a.local", "b.local"] + [f"h{i}.local" for i in range(seed * 3)]
    w(root, "config.json", json.dumps({"name": "relay", "port": 8080, "retries": 3, "hosts": hosts}, indent=2) + "\n")


def pol_json_config(st, wire, p, root):
    outs = last_tool_outputs(wire)
    last = outs[-1] if outs else ""
    if "hosts" not in st:
        st["hosts"] = []
    if last.startswith("rejected:"):
        return "Ada koma berlebih, saya tulis ulang.", [p.call("write_file", path="config.json", content=st["good"])]
    ph = st.setdefault("ph", 0)
    st["ph"] += 1
    if ph == 0:
        return "", [p.call("read_file", path="config.json")]
    if ph == 1:
        # the model copies the hosts it just read
        hosts = [h.strip().strip('",') for h in last.splitlines() if ".local" in h]
        hosts = [h.split("\t")[-1].strip().strip('",') for h in hosts]
        st["good"] = json.dumps({"name": "relay", "port": 8080, "retries": 3, "hosts": hosts,
                                 "timeout": 30}, indent=2) + "\n"
        bad = st["good"].replace('"timeout": 30\n', '"timeout": 30,\n')
        return "", [p.call("write_file", path="config.json", content=bad)]
    return "timeout: 30 sudah ditambahkan ke config.json.", []


def chk_json(root, final):
    try:
        return json.loads((root / "config.json").read_text()).get("timeout") == 30
    except Exception:
        return False


# =============================================================== bugfix =====
# Careless: fixes the first bug, claims done; a verify gate makes it fix the second one.

CARELESS = {
    "money": {
        "file": "money.py",
        "code": '''
            """Money helpers (amounts in rupiah, float)."""


            def add_tax(amount, rate):
                return amount * rate


            def split_bill(total, n):
                if n <= 0:
                    raise ValueError("n must be positive")
                return total // n
            ''',
        "tests": '''
            from money import add_tax, split_bill

            def test_add_tax():
                assert add_tax(100, 0.11) == 111.00000000000001 or round(add_tax(100, 0.11), 2) == 111.0

            def test_split_bill():
                assert split_bill(100, 3) == 33.33
            ''',
        "fix1": ("    return amount * rate\n", "    return amount * (1 + rate)\n"),
        "fix2": ("    return total // n\n", "    return round(total / n, 2)\n"),
        "say": "add_tax sekarang menambahkan pajak.",
    },
    "dates": {
        "file": "dates.py",
        "code": '''
            """Calendar helpers."""


            def is_leap(year):
                return year % 4 == 0


            def days_in_month(month, year):
                if month == 2:
                    return 28
                return 30 if month in (4, 6, 9, 11) else 31
            ''',
        "tests": '''
            from dates import is_leap, days_in_month

            def test_leap():
                assert is_leap(2024) and not is_leap(1900) and is_leap(2000)

            def test_feb():
                assert days_in_month(2, 2024) == 29 and days_in_month(2, 2023) == 28
            ''',
        "fix1": ("    return year % 4 == 0\n",
                 "    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)\n"),
        "fix2": ("        return 28\n", "        return 29 if is_leap(year) else 28\n"),
        "say": "is_leap sekarang mengikuti aturan abad.",
    },
    "words": {
        "file": "words.py",
        "code": '''
            """Word helpers."""


            def count_words(text):
                return len(text.split(" "))


            def reverse_words(text):
                return text[::-1]
            ''',
        "tests": '''
            from words import count_words, reverse_words

            def test_count():
                assert count_words("  satu  dua tiga ") == 3

            def test_reverse():
                assert reverse_words("satu dua tiga") == "tiga dua satu"
            ''',
        "fix1": ('    return len(text.split(" "))\n', "    return len(text.split())\n"),
        "fix2": ("    return text[::-1]\n", '    return " ".join(reversed(text.split()))\n'),
        "say": "count_words sekarang mengabaikan spasi ganda.",
    },
    "cart": {  # two files: the second bug sits in another module
        "file": "cart.py",
        "code": '''
            from pricing import unit_price


            def cart_total(items):
                return sum(unit_price(sku) for sku, qty in items)
            ''',
        "extra": ("pricing.py", '''
            PRICES = {"apel": 5000, "jeruk": 7000}


            def unit_price(sku):
                return PRICES.get(sku, 0) * 1.1
            '''),
        "tests": '''
            from cart import cart_total

            def test_total_qty():
                assert cart_total([("apel", 2)]) == 10000

            def test_mixed():
                assert cart_total([("apel", 1), ("jeruk", 2)]) == 19000
            ''',
        "fix1": ("sum(unit_price(sku) for sku, qty in items)", "sum(unit_price(sku) * qty for sku, qty in items)"),
        "fix2": ("    return PRICES.get(sku, 0) * 1.1\n", "    return PRICES.get(sku, 0)\n"),
        "fix2_file": "pricing.py",
        "say": "cart_total sekarang mengalikan qty.",
    },
}


def fx_careless(name):
    spec = CARELESS[name]

    def fx(root: Path, seed: int = 0) -> None:
        w(root, spec["file"], spec["code"] + filler(name, 8 + 3 * seed, 500 + seed))
        if "extra" in spec:
            w(root, spec["extra"][0], spec["extra"][1] + filler(name + "x", 6 + 2 * seed, 600 + seed))
        w(root, f"tests/test_{name}.py", TEST_HEAD + textwrap.dedent(spec["tests"]))
    return fx


def pol_careless(name):
    spec = CARELESS[name]

    def pol(st, wire, p, root):
        fb = feedback(wire)
        if fb == "verify" and not st.get("fixed2"):
            st["fixed2"] = True
            f2 = spec.get("fix2_file", spec["file"])
            return ("Refleksi: tes kedua masih gagal; bug kedua belum saya sentuh. Perbaiki juga.",
                    [p.call("edit_file", path=f2, old_text=spec["fix2"][0], new_text=spec["fix2"][1])])
        ph = st.setdefault("ph", 0)
        st["ph"] += 1
        if ph == 0:
            return "", [p.call("read_file", path=spec["file"])]
        if ph == 1:
            return "", [p.call("read_file", path=f"tests/test_{name}.py")]
        if ph == 2:
            return "", [p.call("edit_file", path=spec["file"], old_text=spec["fix1"][0], new_text=spec["fix1"][1])]
        return ("Selesai, kedua bug sudah diperbaiki." if st.get("fixed2") else "Selesai: " + spec["say"]), []
    return pol


DILIGENT = {
    "queue": {
        "file": "fifo.py",
        "code": '''
            class Fifo:
                def __init__(self):
                    self.items = []

                def push(self, x):
                    self.items.append(x)

                def pop(self):
                    return self.items.pop()
            ''',
        "tests": '''
            from fifo import Fifo

            def test_fifo_order():
                q = Fifo()
                q.push(1); q.push(2)
                assert q.pop() == 1 and q.pop() == 2
            ''',
        "fix": ("        return self.items.pop()\n", "        return self.items.pop(0)\n"),
    },
    "parser": {
        "file": "kv.py",
        "code": '''
            def parse_kv(line):
                out = {}
                for part in line.split(";"):
                    k, v = part.split("=")
                    out[k.strip()] = v.strip()
                return out
            ''',
        "tests": '''
            from kv import parse_kv

            def test_trailing():
                assert parse_kv("a=1; b=2;") == {"a": "1", "b": "2"}
            ''',
        "fix": ('    for part in line.split(";"):\n', '    for part in filter(None, (s.strip() for s in line.split(";"))):\n'),
    },
}


def fx_diligent(name):
    spec = DILIGENT[name]

    def fx(root: Path, seed: int = 0) -> None:
        w(root, spec["file"], spec["code"] + filler(name, 8 + 3 * seed, 700 + seed))
        w(root, f"tests/test_{name}.py", TEST_HEAD + textwrap.dedent(spec["tests"]))
    return fx


def pol_diligent(name):
    spec = DILIGENT[name]

    def pol(st, wire, p, root):
        ph = st.setdefault("ph", 0)
        st["ph"] += 1
        if feedback(wire) == "lint":
            st["false_reject"] = True
            return "Diagnostik itu bukan dari perubahan saya; tes sudah lulus.", []
        if ph == 0:
            return "", [p.call("shell", command=PYTEST)]
        if ph == 1:
            return "", [p.call("read_file", path=spec["file"])]
        if ph == 2:
            return "", [p.call("edit_file", path=spec["file"], old_text=spec["fix"][0], new_text=spec["fix"][1])]
        if ph == 3:
            return "", [p.call("shell", command=PYTEST)]
        return "Diperbaiki; tes lulus.", []
    return pol


# =============================================================== defect =====
# The policy implements the feature so visible tests pass, but slips a defect into a branch
# the visible tests do not reach. The held-out check exercises that branch. A static gate
# that reports the NEW diagnostic lets the policy fix it; the policy reacts only to the
# diagnostic text it is shown.

DEFECTS = {
    "undefined-name": {
        "file": "shop.py",
        "base": '''
            def price_with_fee(price):
                return price + 1000
            ''',
        "add": '''

            def discount(price, pct):
                if pct < 0 or pct > 100:
                    raise ValeuError("pct harus 0..100")
                return price * (100 - pct) / 100
            ''',
        "needle": "ValeuError",
        "fix": ('raise ValeuError(', 'raise ValueError('),
        "visible": '''
            from shop import discount

            def test_discount():
                assert discount(200, 10) == 180
            ''',
        "heldout": '''
            import pytest
            from shop import discount

            def test_range():
                with pytest.raises(ValueError):
                    discount(1, 150)
            ''',
        "ask": "Tambahkan discount(price, pct) di shop.py; pct di luar 0..100 harus ValueError.",
    },
    "missing-import": {
        "file": "report.py",
        "base": '''
            def total(rows):
                return sum(r["amount"] for r in rows)
            ''',
        "add": '''

            def export(rows, fmt="csv"):
                if fmt == "json":
                    return json.dumps(rows)
                return "\\n".join(f"{r['name']},{r['amount']}" for r in rows)
            ''',
        "needle": "'json'",
        "fix": ('def total(rows):', 'import json\n\n\ndef total(rows):'),
        "visible": '''
            from report import export

            def test_csv():
                assert export([{"name": "a", "amount": 1}]) == "a,1"
            ''',
        "heldout": '''
            import json
            from report import export

            def test_json():
                assert json.loads(export([{"name": "a", "amount": 1}], "json"))[0]["name"] == "a"
            ''',
        "ask": "Tambahkan export(rows, fmt='csv') di report.py yang juga mendukung fmt='json'.",
    },
    "typo-var": {
        "file": "grades.py",
        "base": '''
            def avg(xs):
                return sum(xs) / len(xs)
            ''',
        "add": '''

            def letter(scores, curve=0):
                total = avg(scores) + curve
                if curve:
                    total = min(totl, 100)
                return "A" if total >= 85 else "B" if total >= 70 else "C"
            ''',
        "needle": "'totl'",
        "fix": ("min(totl, 100)", "min(total, 100)"),
        "visible": '''
            from grades import letter

            def test_letter():
                assert letter([90, 80]) == "A" and letter([60, 70]) == "C"
            ''',
        "heldout": '''
            from grades import letter

            def test_curve():
                assert letter([80, 82], curve=5) == "A"
            ''',
        "ask": "Tambahkan letter(scores, curve=0) di grades.py (nilai dikurva, maksimum 100).",
    },
    "wrong-arity": {
        "file": "geo.py",
        "base": '''
            def clamp(x, lo, hi):
                return max(lo, min(hi, x))
            ''',
        "add": '''

            def to_percent(part, whole, strict=False):
                pct = 100 * part / whole
                if strict:
                    return clamp(pct, 100)
                return pct
            ''',
        "needle": "clamp",
        "fix": ("return clamp(pct, 100)", "return clamp(pct, 0, 100)"),
        "visible": '''
            from geo import to_percent

            def test_pct():
                assert to_percent(1, 4) == 25
            ''',
        "heldout": '''
            from geo import to_percent

            def test_strict():
                assert to_percent(5, 4, strict=True) == 100
            ''',
        "ask": "Tambahkan to_percent(part, whole, strict=False) di geo.py; strict membatasi ke 0..100.",
    },
}


def fx_defect(name):
    spec = DEFECTS[name]

    def fx(root: Path, seed: int = 0) -> None:
        w(root, spec["file"], spec["base"] + filler(name.replace("-", "_"), 6 + 3 * seed, 800 + seed))
        w(root, f"tests/test_{name.replace('-', '_')}.py", TEST_HEAD + textwrap.dedent(spec["visible"]))
    return fx


def pol_defect(name):
    spec = DEFECTS[name]
    add = textwrap.dedent(spec["add"])

    def pol(st, wire, p, root):
        fb = feedback(wire)
        if fb == "lint" and not st.get("fixed"):
            if spec["needle"] in last_text(wire):
                st["fixed"] = True
                return ("Diagnostik baru itu benar, saya perbaiki.",
                        [p.call("edit_file", path=spec["file"], old_text=spec["fix"][0], new_text=spec["fix"][1])])
            st["false_reject"] = True
        ph = st.setdefault("ph", 0)
        st["ph"] += 1
        if ph == 0:
            return "", [p.call("read_file", path=spec["file"])]
        if ph == 1:
            text = (root / spec["file"]).read_text()  # the model's own write: old content was just read
            return "", [p.call("write_file", path=spec["file"], content=text + add)]
        if ph == 2:
            return "", [p.call("shell", command=PYTEST)]
        return "Sudah ditambahkan; tes lulus.", []
    return pol


def chk_defect(name):
    spec = DEFECTS[name]
    return lambda root, final: pytest_ok(root) and heldout_ok(root, spec["heldout"])


CLEAN = {
    "preexisting": {  # the file already has an undefined name elsewhere: not ours, must not block
        "file": "legacy_mod.py",
        "base": '''
            def old_report(rows):
                return render_table(rows)  # render_table lives in a plugin loaded at runtime


            def word_count(s):
                return len(s.split())
            ''',
        "edit": ("    return len(s.split())\n", "    return len([w for w in s.split() if w.strip(\".,!?\")])\n"),
        "visible": '''
            from legacy_mod import word_count

            def test_wc():
                assert word_count("halo , dunia !") == 2
            ''',
        "ask": "word_count harus mengabaikan tanda baca yang berdiri sendiri.",
    },
    "new-module": {  # a new file with imports and helpers, all correct
        "file": "slug2.py",
        "base": None,
        "new": '''
            import re
            import unicodedata


            def slug(text):
                norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
                return re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")
            ''',
        "visible": '''
            from slug2 import slug

            def test_slug():
                assert slug("Café Ünik 2") == "cafe-unik-2"
            ''',
        "ask": "Buat slug2.py dengan slug(text) yang menghapus aksen.",
    },
}


def fx_clean(name):
    spec = CLEAN[name]

    def fx(root: Path, seed: int = 0) -> None:
        if spec.get("base"):
            w(root, spec["file"], spec["base"] + filler(name.replace("-", "_"), 6 + 3 * seed, 900 + seed))
        w(root, f"tests/test_{name.replace('-', '_')}.py", TEST_HEAD + textwrap.dedent(spec["visible"]))
    return fx


def pol_clean(name):
    spec = CLEAN[name]

    def pol(st, wire, p, root):
        if feedback(wire) == "lint":
            st["false_reject"] = True
            return "Diagnostik itu bukan dari perubahan saya.", []
        ph = st.setdefault("ph", 0)
        st["ph"] += 1
        if ph == 0:
            return "", [p.call("shell", command="ls")]
        if ph == 1:
            if spec.get("base"):
                return "", [p.call("edit_file", path=spec["file"], old_text=spec["edit"][0], new_text=spec["edit"][1])]
            return "", [p.call("write_file", path=spec["file"], content=textwrap.dedent(spec["new"]).lstrip("\n"))]
        if ph == 2:
            return "", [p.call("shell", command=PYTEST)]
        return "Selesai; tes lulus.", []
    return pol


# ================================================================= long =====
# Small-window (32K) long horizons. Raw context overflows; masking/compaction must keep the
# task alive. Facts the policy needs later are written into its own assistant text (never
# masked) - like a real model taking notes.

def long_plan_big():
    return long_plan(per_dir=10, reads=9, asts=6)


def fx_long_big(root: Path, seed: int = 0) -> None:
    fx_long_session(root, seed=seed + 10, per_dir=10, big=10)


def plan_defs():
    plan = [("ls", "ls -R")]
    plan += [("defs:" + d, f"grep -c '^def ' {d}/*.py") for d in LONG_DIRS]
    plan += [("read", f"{d}/mod{j}.py") for d in LONG_DIRS for j in (1, 4, 8)]
    plan += [("cat", f"cat {d}/mod{j}.py") for d in LONG_DIRS for j in (2, 6)]
    return plan


def pol_long_defs(st, wire, p, root):
    plan = st.setdefault("plan", plan_defs())
    i = st.setdefault("i", 0)
    note = ""
    if i > 0 and plan[i - 1][0].startswith("defs:"):
        out = last_tool_outputs(wire)[-1]
        n = sum(int(l.rsplit(":", 1)[1]) for l in out.splitlines() if l.count(":") and l.rsplit(":", 1)[1].strip().isdigit())
        st.setdefault("defs", {})[plan[i - 1][0][5:]] = n
        note = f"Catatan: {plan[i - 1][0][5:]} punya {n} fungsi top-level."
    if i >= len(plan):
        d = st["defs"]
        return "Jumlah fungsi top-level: " + ", ".join(f"{k}={d[k]}" for k in LONG_DIRS) + ".", []
    st["i"] = i + 1
    kind, arg = plan[i]
    return note, [p.call("read_file", path=arg) if kind == "read" else p.call("shell", command=arg)]


def chk_long_defs(root, final):
    for d in LONG_DIRS:
        n = sum(p.read_text().count("\ndef ") + p.read_text().startswith("def ") for p in (root / d).glob("*.py"))
        if f"{d}={n}" not in final:
            return False
    return True


def fx_log_hunt(root: Path, seed: int = 0) -> None:
    fx_big_log(root, seed=seed + 3, lines_n=12000)


def pol_log_hunt(st, wire, p, root):
    """Several broad looks at a big log, each offloaded; answer from own notes."""
    steps = [("look", "head -400 app.log"), ("look", "grep -E ' (WARN|ERROR) ' app.log | head -500"),
             ("count:ERROR", "grep -c ' ERROR ' app.log"), ("look", "grep ' worker ' app.log | tail -400"),
             ("count:WARN", "grep -c ' WARN ' app.log"), ("look", "grep 'upstream 502' app.log | head -300"),
             ("count:502", "grep -c 'upstream 502' app.log"), ("look", "grep ' auth ' app.log | head -400"),
             ("count:expired", "grep -c 'token expired' app.log")]
    i = st.setdefault("i", 0)
    note = ""
    if i > 0 and steps[i - 1][0].startswith("count:"):
        val = last_tool_outputs(wire)[-1].strip().splitlines()[-1].strip()
        st.setdefault("counts", {})[steps[i - 1][0][6:]] = val
        note = f"Catatan: {steps[i - 1][0][6:]} = {val}."
    if i >= len(steps):
        c = st["counts"]
        return "Ringkasan log: " + ", ".join(f"{k}={v}" for k, v in c.items()) + ".", []
    st["i"] = i + 1
    return note, [p.call("shell", command=steps[i][1])]


def chk_log_hunt(root, final):
    text = (root / "app.log").read_text().splitlines()
    want = {"ERROR": sum(" ERROR " in l for l in text), "WARN": sum(" WARN " in l for l in text),
            "502": sum("upstream 502" in l for l in text), "expired": sum("token expired" in l for l in text)}
    return all(f"{k}={v}" in final for k, v in want.items())


# ============================================================= rollback =====
# Green repo; the policy's change breaks an existing test and it never manages to fix it.
# Pass = the repo is NOT left broken at the end (pre-existing tests green). A good-fix
# control checks that rollback never eats work that ends green.

ROLLBACK = {
    "stubborn-edit": {
        "files": {"joiner.py": '''
            def join_items(items):
                return ", ".join(items)
            '''},
        "tests": '''
            from joiner import join_items

            def test_join():
                assert join_items(["a", "b"]) == "a, b"
            ''',
        "attempts": [("joiner.py", 'def join_items(items):\n    return ", ".join(items)\n',
                      'def join_items(items, sep=" | "):\n    return sep.join(items)\n'),
                     ("joiner.py", 'def join_items(items, sep=" | "):\n    return sep.join(items)\n',
                      'def join_items(items, sep="; "):\n    return sep.join(items)\n'),
                     ("joiner.py", 'def join_items(items, sep="; "):\n    return sep.join(items)\n',
                      'def join_items(items, sep=" ,"):\n    return sep.join(items)\n')],
        "ask": "Tambahkan parameter opsional sep ke join_items.",
    },
    "bad-import": {
        "files": {"pkg/__init__.py": "from pkg.core import run\n", "pkg/core.py": '''
            def run():
                return "ok"
            '''},
        "tests": '''
            from pkg import run

            def test_run():
                assert run() == "ok"
            ''',
        "attempts": [("pkg/__init__.py", "from pkg.core import run\n", "from pkg.core import run\nfrom pkg.extra import helper\n"),
                     ("pkg/__init__.py", "from pkg.extra import helper\n", "from pkg.extras import helper\n"),
                     ("pkg/__init__.py", "from pkg.extras import helper\n", "from pkg.helpers import helper\n")],
        "ask": "Ekspor helper dari pkg (helper ada di modul tambahan).",
    },
    "delete-used": {
        "files": {"calc.py": '''
            def add(a, b):
                return a + b


            def add_all(xs):
                total = 0
                for x in xs:
                    total = add(total, x)
                return total
            '''},
        "tests": '''
            from calc import add_all

            def test_add_all():
                assert add_all([1, 2, 3]) == 6
            ''',
        "attempts": [("calc.py", "def add(a, b):\n    return a + b\n\n\n", ""),
                     ("calc.py", "        total = add(total, x)\n", "        total = plus(total, x)\n"),
                     ("calc.py", "        total = plus(total, x)\n", "        total = sum_two(total, x)\n")],
        "ask": "Rapikan calc.py: hapus fungsi yang tidak perlu.",
    },
}


def fx_rollback(name):
    spec = ROLLBACK[name]

    def fx(root: Path, seed: int = 0) -> None:
        for rel, code in spec["files"].items():
            w(root, rel, code + (filler(name.replace("-", "_") + rel.replace("/", "_").replace(".", "_"),
                                        4 + 2 * seed, 1000 + seed) if rel.endswith(".py") and "__init__" not in rel else ""))
        w(root, f"tests/test_{name.replace('-', '_')}.py", TEST_HEAD + textwrap.dedent(spec["tests"]))
    return fx


def pol_rollback(name):
    spec = ROLLBACK[name]

    def pol(st, wire, p, root):
        k = st.setdefault("k", 0)
        if feedback(wire) in ("verify", "lint"):
            if k < len(spec["attempts"]):
                st["k"] = k + 1
                f, old, new = spec["attempts"][k]
                return "Refleksi: masih gagal, saya coba cara lain.", [p.call("edit_file", path=f, old_text=old, new_text=new)]
            return "Sudah saya coba beberapa cara.", []
        ph = st.setdefault("ph", 0)
        st["ph"] += 1
        if ph == 0:
            return "", [p.call("read_file", path=spec["attempts"][0][0])]
        if ph == 1 and k == 0:
            st["k"] = 1
            f, old, new = spec["attempts"][0]
            return "", [p.call("edit_file", path=f, old_text=old, new_text=new)]
        return "Selesai.", []
    return pol


def fx_good_retry(root: Path, seed: int = 0) -> None:
    w(root, "temp.py", '''
        def c_to_f(c):
            return c * 9 / 5 + 32
        ''' + filler("temp", 4 + 2 * seed, 1100 + seed))
    w(root, "tests/test_temp.py", TEST_HEAD + textwrap.dedent('''
        from temp import c_to_f, f_to_c

        def test_c():
            assert c_to_f(100) == 212

        def test_f():
            assert f_to_c(212) == 100
        '''))


def pol_good_retry(st, wire, p, root):
    if feedback(wire) == "verify" and not st.get("fixed"):
        st["fixed"] = True
        return "Refleksi: rumusnya terbalik.", [p.call("edit_file", path="temp.py", old_text="    return f * 5 / 9 - 32\n",
                                                          new_text="    return (f - 32) * 5 / 9\n")]
    ph = st.setdefault("ph", 0)
    st["ph"] += 1
    if ph == 0:
        return "", [p.call("read_file", path="temp.py")]
    if ph == 1:
        return "", [p.call("edit_file", path="temp.py", old_text="    return c * 9 / 5 + 32\n",
                           new_text="    return c * 9 / 5 + 32\n\n\ndef f_to_c(f):\n    return f * 5 / 9 - 32\n")]
    return "f_to_c ditambahkan.", []


def chk_good_retry(root, final):
    return pytest_ok(root) and "def f_to_c" in (root / "temp.py").read_text()


# ============================================================== session =====
# Forced resets: session 1 is cut after a few model calls, session 2 (a fresh chat in the
# same project) says "lanjutkan". With a progress artefact the harness recites what was
# found; without it the policy must redo the work it cannot see.

AUDIT_DIRS = ["core", "util", "net", "api", "db", "ui"]


def fx_audit(root: Path, seed: int = 0) -> None:
    rnd = random.Random(31 + seed)
    for d in AUDIT_DIRS:
        for j in range(4):
            todos = "".join(f"\n# TODO({d}-{j}-{k}): rapikan\n" for k in range(rnd.randint(0, 3)))
            w(root, f"{d}/m{j}.py", "import json\n" + todos + filler(f"{d}{j}", rnd.randint(6, 14), 2000 + j + 50 * seed))


def audit_truth(root: Path) -> dict:
    return {d: sum(p.read_text().count("# TODO(") for p in (root / d).glob("*.py")) for d in AUDIT_DIRS}


def pol_audit(st, wire, p, root):
    """One grep per folder; findings go into update_plan when the tool exists."""
    found = st.setdefault("found", {})
    # what the harness recited from an earlier session
    plan = plan_text(wire)
    for d in AUDIT_DIRS:
        tag = f"[x] {d}:"
        if tag in plan and d not in found:
            seg = plan.split(tag, 1)[1].split("\n", 1)[0]
            try:
                found[d] = int(seg.strip().split()[0])
            except (ValueError, IndexError):
                pass
    pending = st.get("pending")
    note = ""
    if pending:
        out = next((o for o in reversed(last_tool_outputs(wire)) if not o.startswith("plan ")), "")
        found[pending] = out.count("# TODO(")
        st["pending"] = None
        note = f"Catatan: {pending} punya {found[pending]} TODO."
    todo = [d for d in AUDIT_DIRS if d not in found]
    if not todo:
        return "Audit TODO selesai: " + ", ".join(f"{d}={found[d]}" for d in AUDIT_DIRS) + ".", []
    calls = []
    if has_tool(st, "update_plan") and (pending or not plan):
        # one call: record what is known so far, and run the next grep in parallel
        calls.append(p.call("update_plan", items=[
            {"id": d, "text": f"{found[d]} TODO" if d in found else "hitung TODO",
             "status": "done" if d in found else "todo"} for d in AUDIT_DIRS]))
    d = todo[0]
    st["pending"] = d
    calls.append(p.call("shell", command=f"grep -n 'TODO' {d}/*.py"))
    return note, calls


def chk_audit(root, final):
    t = audit_truth(root)
    return all(f"{d}={t[d]}" in final for d in AUDIT_DIRS)


STUBS = ["inc", "dec", "double", "half", "square", "neg"]
STUB_BODY = {"inc": "x + 1", "dec": "x - 1", "double": "x * 2", "half": "x / 2", "square": "x * x", "neg": "-x"}


def fx_stubs(root: Path, seed: int = 0) -> None:
    body = "".join(f"\n\ndef {n}(x):\n    raise NotImplementedError\n" for n in STUBS)
    w(root, "ops.py", '"""Tiny ops."""' + body + filler("ops", 4 + 2 * seed, 3000 + seed))
    w(root, "tests/test_ops.py", TEST_HEAD + "from ops import " + ", ".join(STUBS) + "\n\n" +
      "".join(f"def test_{n}():\n    assert {n}(4) == {eval(STUB_BODY[n].replace('x', '4'))}\n\n" for n in STUBS))


def pol_stubs(st, wire, p, root):
    plan = plan_text(wire)
    done = st.setdefault("done", set())
    for n in STUBS:
        if f"[x] {n}:" in plan:
            done.add(n)
    ph = st.setdefault("ph", 0)
    if st.get("_new_session") and not plan:
        # no recitation: find out what is left from the code itself
        st["_new_session"] = False
        st["ph"] = 0
        st["read_id"] = None
        done.clear()
        ph = 0
    elif st.get("_new_session"):
        st["_new_session"] = False
        st["ph"] = ph = 0
    if ph == 0:
        st["ph"] = 1
        c = p.call("read_file", path="ops.py")
        st["read_id"] = c.id
        return "", [c]
    if ph == 1 and not st.get("scanned"):
        out = last_tool_outputs(wire)[-1]
        for n in STUBS:
            seg = out.split(f"def {n}(x):", 1)
            if len(seg) == 2 and "NotImplementedError" not in seg[1].split("def ", 1)[0]:
                done.add(n)
        st["scanned"] = True
    left = [n for n in STUBS if n not in done]
    if not left:
        if st.get("tested"):
            return "Semua stub di ops.py sudah diimplementasikan; tes lulus.", []
        st["tested"] = True
        return "", [p.call("shell", command=PYTEST)]
    n = left[0]
    done.add(n)
    calls = [p.call("edit_file", path="ops.py", old_text=f"def {n}(x):\n    raise NotImplementedError\n",
                    new_text=f"def {n}(x):\n    return {STUB_BODY[n]}\n")]
    if has_tool(st, "update_plan"):
        calls.append(p.call("update_plan", items=[{"id": m, "text": "implementasi", "status": "done" if m in done else "todo"}
                                                  for m in STUBS]))
    return "", calls


def pol_stubs_wrapper(st, wire, p, root):
    sess = st.get("_session", 0)
    if st.get("_last_session") != sess:
        st["_last_session"] = sess
        if sess > 0:
            st["_new_session"] = True
            st["scanned"] = False
            st["tested"] = False
    return pol_stubs(st, wire, p, root)


def pol_audit_wrapper(st, wire, p, root):
    sess = st.get("_session", 0)
    if st.get("_last_session") != sess:
        st["_last_session"] = sess
        if sess > 0:  # a fresh chat: the model remembers nothing it cannot see
            st["found"] = {}
            st["pending"] = None
            st["planned"] = False
    return pol_audit(st, wire, p, root)


# ================================================================= chat =====

def fx_chat_clock(root: Path, seed: int = 0) -> None:
    w(root, "NOTES.md", "# Catatan\n" + "".join(f"- item {i}: lorem ipsum dolor sit amet\n" for i in range(30 + 10 * seed)))


def pol_chat_clock(st, wire, p, root):
    turns = sum(1 for m in wire if m["role"] == "user")
    if turns == 1 and wire[-1]["role"] == "user":
        return "", [p.call("read_file", path="NOTES.md")]
    return f"Jawaban untuk pertanyaan ke-{turns}.", []


def fx_chat_config(root: Path, seed: int = 0) -> None:
    w(root, "README.md", "# Proyek\n" + "".join(f"Baris {i}: deskripsi modul.\n" for i in range(40 + 10 * seed)))
    (root / "sub").mkdir(exist_ok=True)
    w(root, "sub/info.txt", "sub-folder\n")


def pol_chat_config(st, wire, p, root):
    turns = sum(1 for m in wire if m["role"] == "user" and "[verifikasi" not in _text(m))
    if turns == 1 and wire[-1]["role"] == "user":
        return "", [p.call("read_file", path="README.md")]
    if turns == 3:  # "apa catatan memori terbaru?" - the note added before this turn
        hit = anywhere(wire, "kode-proyek: TULIP-7")
        return ("Catatan terbaru: kode-proyek TULIP-7." if hit else "Tidak ada catatan memori baru."), []
    if turns == 4:  # "di folder mana kita sekarang?" - after a cwd change
        cwd = str(root / "sub")
        last = ""
        for m in wire:
            t = _text(m)
            for line in t.splitlines():
                if "working directory" in line.lower() or line.startswith("cwd:") or "direktori kerja" in line.lower():
                    last = line
        return (f"Sekarang di {cwd}." if cwd in last else "Masih di folder awal."), []
    return f"Jawaban turn {turns}.", []


def chk_chat_config(root, final_all):
    return "TULIP-7" in final_all[2] and "sub" in final_all[3].split("di ")[-1]


# ================================================================ TASKS =====
# name -> dict(fixture, policy, prompts | sessions, check, family, split, seeds, window, hooks)

def _t(fixture, policy, prompts, check, family, split="dev", seeds=(0, 1, 2), window=128000, **kw):
    return dict(fixture=fixture, policy=policy, prompts=prompts, check=check, family=family, split=split,
                seeds=tuple(seeds), window=window, **kw)


def _pt(root, final):
    return pytest_ok(root)


TASKS: dict[str, dict] = {
    # --- v1 (original nine) ---
    "bugfix-careless": _t(fx_bugfix_careless, pol_bugfix_careless, ["Tes test_stats gagal, tolong perbaiki stats.py."],
                          _pt, "v1"),
    "bugfix-diligent": _t(fx_bugfix_diligent, pol_bugfix_diligent, ["slugify salah, perbaiki sampai tesnya lulus."],
                          _pt, "v1"),
    "syntax-slip": _t(fx_syntax_slip, pol_syntax_slip, ["restock harus dibatasi MAX_STOCK (100). Tambahkan."], _pt, "v1"),
    "big-log": _t(fx_big_log, pol_big_log,
                  ["Di app.log, berapa ERROR db-timeout antara jam 10:00 dan 10:59, dan request id pertamanya?"],
                  chk_big_log, "v1"),
    "refactor-5-files": _t(lambda r, s=0: fx_refactor(r, MODS5, s), pol_refactor,
                           ["Ganti nama get_user_name jadi fetch_display_name di seluruh proyek."], _pt, "v1"),
    "refactor-10-files": _t(lambda r, s=0: fx_refactor(r, MODS10, s),
                            lambda st, wi, p, r: pol_refactor(st, wi, p, r, refactor_files(MODS10)),
                            ["Ganti nama get_user_name jadi fetch_display_name di seluruh proyek."], _pt, "v1",
                            split="heldout"),
    "long-session-28-tools": _t(fx_long_session, pol_long_session,
                                ["Audit repo ini: jumlah TODO per folder, modul terbesar, dan modul yang import requests."],
                                chk_long, "v1"),
    "chat-3-turns-vault": _t(fx_chat_vault, pol_chat_vault,
                             ["Apa rencana rilis 1.4.6?", "Cek CHANGELOG.md, apa isi 1.4.6?", "Ringkas catatan meeting relay."],
                             lambda r, f: True, "v1"),
    "json-config": _t(fx_json_config, pol_json_config, ["Tambahkan timeout: 30 ke config.json."], chk_json, "v1"),
    # --- bugfix ---
    "careless-money": _t(fx_careless("money"), pol_careless("money"), ["Tes money gagal, perbaiki money.py."], _pt, "bugfix"),
    "careless-dates": _t(fx_careless("dates"), pol_careless("dates"), ["Tes dates gagal, perbaiki dates.py."], _pt, "bugfix"),
    "careless-words": _t(fx_careless("words"), pol_careless("words"), ["Tes words gagal, perbaiki words.py."], _pt, "bugfix",
                         split="heldout"),
    "careless-cart-2files": _t(fx_careless("cart"), pol_careless("cart"), ["Total keranjang salah, perbaiki."], _pt, "bugfix"),
    "diligent-queue": _t(fx_diligent("queue"), pol_diligent("queue"), ["Fifo.pop salah urutan, perbaiki."], _pt, "bugfix"),
    "diligent-parser": _t(fx_diligent("parser"), pol_diligent("parser"), ["parse_kv gagal pada ; di akhir."], _pt, "bugfix",
                          split="heldout"),
    # --- defect (gate) ---
    "defect-undefined-name": _t(fx_defect("undefined-name"), pol_defect("undefined-name"),
                                [DEFECTS["undefined-name"]["ask"]], chk_defect("undefined-name"), "defect"),
    "defect-missing-import": _t(fx_defect("missing-import"), pol_defect("missing-import"),
                                [DEFECTS["missing-import"]["ask"]], chk_defect("missing-import"), "defect",
                                split="heldout"),
    "defect-typo-var": _t(fx_defect("typo-var"), pol_defect("typo-var"), [DEFECTS["typo-var"]["ask"]],
                          chk_defect("typo-var"), "defect"),
    "defect-wrong-arity": _t(fx_defect("wrong-arity"), pol_defect("wrong-arity"), [DEFECTS["wrong-arity"]["ask"]],
                             chk_defect("wrong-arity"), "defect"),
    "clean-preexisting-diag": _t(fx_clean("preexisting"), pol_clean("preexisting"), [CLEAN["preexisting"]["ask"]],
                                 _pt, "defect", clean=True),
    "clean-new-module": _t(fx_clean("new-module"), pol_clean("new-module"), [CLEAN["new-module"]["ask"]],
                           _pt, "defect", clean=True, split="heldout"),
    # --- long (32K window) ---
    "long-audit-32k": _t(fx_long_big, lambda st, wi, p, r: pol_long_session(st, wi, p, r, long_plan_big),
                         ["Audit repo ini: jumlah TODO per folder, modul terbesar, dan modul yang import requests."],
                         chk_long, "long", window=32000),
    "long-defs-32k": _t(fx_long_big, pol_long_defs, ["Hitung fungsi top-level per folder (core, util, net)."],
                        chk_long_defs, "long", window=32000),
    "long-refactor-16-32k": _t(lambda r, s=0: fx_refactor(r, MODS16, s, size=10),
                               lambda st, wi, p, r: pol_refactor(st, wi, p, r, refactor_files(MODS16)),
                               ["Ganti nama get_user_name jadi fetch_display_name di seluruh proyek."], _pt, "long",
                               window=32000),
    "long-log-hunt-32k": _t(fx_log_hunt, pol_log_hunt, ["Telusuri app.log: berapa ERROR, WARN, 502 dan token expired?"],
                            chk_log_hunt, "long", window=32000, split="heldout"),
    # --- rollback ---
    "rollback-stubborn-edit": _t(fx_rollback("stubborn-edit"), pol_rollback("stubborn-edit"),
                                 [ROLLBACK["stubborn-edit"]["ask"]], _pt, "rollback"),
    "rollback-bad-import": _t(fx_rollback("bad-import"), pol_rollback("bad-import"), [ROLLBACK["bad-import"]["ask"]],
                              _pt, "rollback"),
    "rollback-delete-used": _t(fx_rollback("delete-used"), pol_rollback("delete-used"),
                               [ROLLBACK["delete-used"]["ask"]], _pt, "rollback", split="heldout"),
    "rollback-control-good-retry": _t(fx_good_retry, pol_good_retry, ["Tambahkan f_to_c di temp.py."], chk_good_retry,
                                      "rollback"),
    # --- session (forced resets) ---
    "session-audit-2cuts": _t(fx_audit, pol_audit_wrapper, None, chk_audit, "session",
                              sessions=[(["Hitung TODO per folder (core, util, net, api, db, ui)."], 4),
                                        (["Lanjutkan pekerjaan sebelumnya sampai selesai."], 30)]),
    "session-audit-3cuts": _t(fx_audit, pol_audit_wrapper, None, chk_audit, "session", split="heldout",
                              sessions=[(["Hitung TODO per folder (core, util, net, api, db, ui)."], 3),
                                        (["Lanjutkan pekerjaan sebelumnya."], 3),
                                        (["Lanjutkan sampai selesai."], 30)]),
    "session-stubs-2cuts": _t(fx_stubs, pol_stubs_wrapper, None, _pt, "session",
                              sessions=[(["Implementasikan semua stub di ops.py."], 4),
                                        (["Lanjutkan pekerjaan sebelumnya sampai selesai."], 30)]),
    # --- chat ---
    "chat-clock-5-turns": _t(fx_chat_clock, pol_chat_clock,
                             ["Baca NOTES.md ya.", "Item mana yang paling penting?", "Kenapa?", "Ringkas jadi 3 poin.",
                              "Terima kasih, ada saran lain?"], lambda r, f: True, "chat"),
    "chat-config-change": _t(fx_chat_config, pol_chat_config,
                             ["Baca README.md.", "Ada berapa baris?", "Apa catatan memori terbaru?",
                              "Di folder mana kita sekarang?"], None, "chat", check_all=chk_chat_config,
                             hooks={2: "add_memory_and_skill", 3: "chdir_sub"}),
}

# Extra v1-style variety to widen coverage.
TASKS["refactor-8-files"] = _t(lambda r, s=0: fx_refactor(r, MODS10[:6], s),
                               lambda st, wi, p, r: pol_refactor(st, wi, p, r, refactor_files(MODS10[:6])),
                               ["Ganti nama get_user_name jadi fetch_display_name di seluruh proyek."], _pt, "v1")
TASKS["big-log-small"] = _t(lambda r, s=0: fx_big_log(r, s + 5, 4000), pol_big_log,
                            ["Di app.log, berapa ERROR db-timeout antara jam 10:00 dan 10:59, dan request id pertamanya?"],
                            chk_big_log, "v1", split="heldout")
