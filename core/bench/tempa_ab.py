"""Deterministic A/B replay: legacy harness vs Tempa, through the real Agent loop.

No live model: ``neovarch.agent.stream_chat`` is replaced by a scripted policy per task
that reacts to what the harness shows it (tool output, "rejected:", verify feedback,
masked observations). Tools, files, pytest and the harness code all run for real; what
is simulated is only the model's choices. Token counts use tiktoken cl100k_base on the
exact wire (tools schema + messages) the harness would send.

    python3 bench/tempa_ab.py run <task> <mode>      # one run, prints JSON (used by `all`)
    python3 bench/tempa_ab.py all [out.json]          # every task x mode, serially, subprocess each
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import resource
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE))
RUNS = Path(os.environ.get("TEMPA_BENCH_DIR", "/workspace/work/tempa-bench-runs"))
MODES = ["legacy", "tempa", "tempa-tinggi", "tempa-nomask"]
# Assumed price of a cheap OpenAI-compatible model (USD per 1M tokens). Not a quote.
PRICE_IN, PRICE_CACHED, PRICE_OUT = 0.30, 0.03, 1.20

# ----------------------------------------------------------------- tokens -----

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def ntok(s: str) -> int:
        return len(_ENC.encode(s, disallowed_special=()))
    TOKENIZER = "tiktoken cl100k_base"
except Exception:  # pragma: no cover
    def ntok(s: str) -> int:
        return (len(s) + 3) // 4
    TOKENIZER = "chars/4"


def serialize(tools, messages) -> list[str]:
    """Wire as a list of chunks in provider order (tools first, then messages)."""
    out = [json.dumps(tools, ensure_ascii=False, sort_keys=True)]
    for m in messages:
        out.append(json.dumps({k: m[k] for k in ("role", "content", "tool_calls", "tool_call_id") if k in m},
                              ensure_ascii=False, sort_keys=True))
    return out


# ------------------------------------------------------------- fixtures -----

def w(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    head, sep, rest = text.partition(SENTINEL)
    p.write_text(textwrap.dedent(head).lstrip("\n") + rest, encoding="utf-8")


def D(s: str) -> str:
    return textwrap.dedent(s).lstrip("\n")


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


SENTINEL = "\x00FILLER\x00"


def fx_bugfix_careless(root: Path) -> None:
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
        ''' + filler("stats", 12, 1))
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


def fx_bugfix_diligent(root: Path) -> None:
    w(root, "textutil.py", '''
        import re


        def slugify(text):
            text = re.sub(r"[^A-Za-z0-9]+", "-", text.strip())
            return text.strip("-")


        def truncate(text, n):
            return text if len(text) <= n else text[: n - 1] + "…"
        ''' + filler("text", 10, 2))
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


def fx_syntax_slip(root: Path) -> None:
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
        ''' + filler("inv", 10, 3))
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


LOG_LINES = 20000


def fx_big_log(root: Path) -> None:
    rnd = random.Random(42)
    lines = []
    services = ["api", "worker", "relay", "sync", "auth"]
    for i in range(LOG_LINES):
        h = 8 + (i * 6) // LOG_LINES
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




MODS5 = ["views", "api", "reports"]
MODS10 = ["views", "api", "reports", "admin", "billing", "emails", "search", "export"]


def refactor_files(mods: list[str]) -> list[str]:
    return ["app/users.py"] + [f"app/{m}.py" for m in mods] + ["tests/test_app.py"]


def fx_refactor(root: Path, mods: list[str] = MODS5) -> None:
    w(root, "app/__init__.py", "")
    w(root, "app/users.py", '''
        USERS = {1: {"first": "Ayu", "last": "Lestari"}, 2: {"first": "Raka", "last": "Pratama"}}


        def get_user_name(uid):
            u = USERS[uid]
            return f"{u['first']} {u['last']}"
        ''' + filler("users", 14, 4))
    for i, mod in enumerate(mods):
        w(root, f"app/{mod}.py", f'''
            from app.users import get_user_name


            def {mod}_title(uid):
                return "[{mod}] " + get_user_name(uid)
            ''' + filler(mod, 14, 10 + i))
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
        ''' + filler("tst", 6, 9))
    if len(mods) > 3:
        with (root / "tests/test_app.py").open("a") as fh:
            fh.write("\n\ndef test_more():\n    import importlib\n    for m in %r:\n"
                     "        mod = importlib.import_module('app.' + m)\n"
                     "        assert getattr(mod, m + '_title')(1).endswith('Ayu Lestari')\n" % (mods[3:],))


LONG_DIRS = ["core", "util", "net"]


def fx_long_session(root: Path) -> None:
    rnd = random.Random(7)
    for d in LONG_DIRS:
        for j in range(8):
            todos = "".join(f"\n# TODO({d}-{j}-{k}): handle edge case {k}\n" for k in range(rnd.randint(0, 3)))
            imp = "import requests\n" if rnd.random() < 0.3 else "import json\n"
            w(root, f"{d}/mod{j}.py", imp + todos + filler(f"{d}{j}", rnd.randint(4, 12), 100 + j))
    w(root, "requirements.txt", "requests==2.32.3\npyyaml==6.0.2\n")


def long_truth(root: Path) -> dict:
    todo = {d: sum(p.read_text().count("# TODO(") for p in (root / d).glob("*.py")) for d in LONG_DIRS}
    sizes = {f"{d}/{p.name}": len(p.read_text().splitlines()) for d in LONG_DIRS for p in (root / d).glob("*.py")}
    req = sorted(f"{d}/{p.name}" for d in LONG_DIRS for p in (root / d).glob("*.py") if "import requests" in p.read_text())
    return {"todo": todo, "largest": max(sizes, key=lambda k: (sizes[k], k)), "requests": req}


def fx_chat_vault(root: Path) -> None:
    w(root, "CHANGELOG.md", "# Changelog\n\n## 1.4.6 (belum rilis)\n- Mode ringan di HP\n- Relay baru\n" +
      "".join(f"\n## 1.4.{i}\n- perbaikan kecil {i}\n- peningkatan UI {i}\n" for i in range(5, 0, -1)))
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
        w(vault, f"{k}.md", f"# {k}\n\n{v}\n\n" + (f"Detail {k}: " + "lorem ipsum dolor sit amet " * 40) + "\n")


def fx_json_config(root: Path) -> None:
    w(root, "config.json", json.dumps({"name": "relay", "port": 8080, "retries": 3,
                                       "hosts": ["a.local", "b.local"]}, indent=2) + "\n")


# --------------------------------------------------------------- policies -----

class P:
    """Helpers for scripted policies."""

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
            out.append(str(m.get("content") or ""))
        else:
            break
    return list(reversed(out))


def last_is_verify(wire) -> bool:
    return wire[-1]["role"] == "user" and "[verifikasi otomatis gagal" in str(wire[-1].get("content"))


def visible(wire, call_id: str) -> bool:
    for m in wire:
        if m["role"] == "tool" and m.get("tool_call_id") == call_id:
            return not str(m.get("content") or "").startswith("[output alat lama disembunyikan")
    return False


def pol_bugfix_careless(st, wire, p, root):
    ph = st.setdefault("ph", 0)
    if last_is_verify(wire):
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
    if st.get("median"):
        return "Sudah: mean membagi dengan len(xs) dan median merata-ratakan dua nilai tengah.", []
    return "Sudah saya perbaiki: mean sekarang membagi dengan len(xs).", []


def pol_bugfix_diligent(st, wire, p, root):
    ph = st.setdefault("ph", 0)
    st["ph"] += 1
    if ph == 0:
        return "", [p.call("shell", command="python3 -m pytest -q -p no:cacheprovider")]
    if ph == 1:
        return "", [p.call("read_file", path="textutil.py")]
    if ph == 2:
        return "", [p.call("edit_file", path="textutil.py", old_text='    return text.strip("-")',
                           new_text='    return text.strip("-").lower()')]
    if ph == 3:
        return "", [p.call("shell", command="python3 -m pytest -q -p no:cacheprovider")]
    return "slugify sekarang menurunkan huruf; semua tes lulus.", []


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


def pol_refactor(st, wire, p, root, files=None):
    REFACTOR_FILES = files or refactor_files(MODS5)
    ph = st.setdefault("ph", 0)
    reads = st.setdefault("reads", {})
    edits = st.setdefault("edits", 0)
    if ph == 0:
        st["ph"] = 1
        return "", [p.call("shell", command="grep -rn get_user_name .")]
    if ph == 1:
        f = REFACTOR_FILES[len(reads)]
        c = p.call("read_file", path=f)
        reads[f] = c.id
        if len(reads) == len(REFACTOR_FILES):
            st["ph"] = 2
        return "", [c]
    if ph == 2:
        if edits < len(REFACTOR_FILES):
            f = REFACTOR_FILES[edits]
            if not visible(wire, reads[f]):  # masked away: a real model must look again
                st["rereads"] = st.get("rereads", 0) + 1
                c = p.call("read_file", path=f)
                reads[f] = c.id
                return f"Isi {f} sudah tidak terlihat, baca ulang.", [c]
            st["edits"] = edits + 1
            return "", [p.call("edit_file", path=f, old_text="get_user_name", new_text="fetch_display_name",
                               replace_all=True)]
        st["ph"] = 3
        return "", [p.call("shell", command="python3 -m pytest -q -p no:cacheprovider")]
    return f"get_user_name diganti fetch_display_name di {len(REFACTOR_FILES)} file; tes lulus.", []


def long_plan():
    plan = [("ls", "ls -R")]
    plan += [("todo:" + d, f"grep -n 'TODO' {d}/*.py") for d in LONG_DIRS]
    plan += [("wc", "wc -l core/*.py util/*.py net/*.py")]
    plan += [("read", f"{d}/mod{j}.py") for d in LONG_DIRS for j in (0, 3, 5)][:8]
    plan += [("req", "grep -rln 'import requests' core util net")]
    plan += [("ast", f"python3 -c \"import ast,sys;t=ast.parse(open('{d}/mod{j}.py').read());"
                     f"print([(n.name,n.lineno,len(ast.dump(n))) for n in t.body if isinstance(n,ast.FunctionDef)])\"")
             for d in LONG_DIRS for j in (1, 2, 4, 6)]
    plan += [("cat", "cat requirements.txt")]
    return plan


def pol_long_session(st, wire, p, root):
    plan = st.setdefault("plan", long_plan())
    i = st.setdefault("i", 0)
    note = ""
    if i > 0:
        kind = plan[i - 1][0]
        out = last_tool_outputs(wire)[-1]
        if kind.startswith("todo:"):
            n = out.count("# TODO(")
            st.setdefault("todo", {})[kind[5:]] = n
            note = f"Catatan: {kind[5:]} punya {n} TODO."
        elif kind == "wc":
            rows = [l.split() for l in out.splitlines()[1:] if l.strip().endswith(".py")]
            best = max(rows, key=lambda r: (int(r[0]), r[1]))
            st["largest"] = best[1]
            note = f"Catatan: modul terbesar {best[1]} ({best[0]} baris)."
        elif kind == "req":
            st["requests"] = sorted(l.strip() for l in out.splitlines()[1:] if l.strip().endswith(".py"))
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


def pol_chat_vault(st, wire, p, root):
    user_turns = sum(1 for m in wire if m["role"] == "user")
    if user_turns == 2 and wire[-1]["role"] == "user":
        return "", [p.call("read_file", path="CHANGELOG.md")]
    if user_turns == 1:
        return "Rencana 1.4.6: ppt-master, relay dan skill baru dirilis bersamaan.", []
    if user_turns == 2:
        return "CHANGELOG 1.4.6 berisi Mode ringan di HP dan relay baru.", []
    return "Meeting relay: endpoint baru, retry eksponensial, diuji di jaringan HP lambat.", []


def pol_json_config(st, wire, p, root):
    outs = last_tool_outputs(wire)
    last = outs[-1] if outs else ""
    good = json.dumps({"name": "relay", "port": 8080, "retries": 3, "hosts": ["a.local", "b.local"],
                       "timeout": 30}, indent=2) + "\n"
    if last.startswith("rejected:"):
        return "Ada koma berlebih, saya tulis ulang.", [p.call("write_file", path="config.json", content=good)]
    ph = st.setdefault("ph", 0)
    st["ph"] += 1
    if ph == 0:
        return "", [p.call("read_file", path="config.json")]
    if ph == 1:
        bad = good.replace('"timeout": 30\n', '"timeout": 30,\n')
        return "", [p.call("write_file", path="config.json", content=bad)]
    return "timeout: 30 sudah ditambahkan ke config.json.", []


# ----------------------------------------------------------------- checks -----

def pytest_ok(root: Path) -> bool:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=root,
                       capture_output=True, text=True, timeout=120)
    return r.returncode == 0


def chk_big_log(root, final):
    n, rid = big_log_truth(root)
    return f"Ada {n} " in final and rid in final


def chk_long(root, final):
    t = long_truth(root)
    return (all(f"{d}={t['todo'][d]}" in final for d in LONG_DIRS) and t["largest"] in final
            and all(r in final for r in t["requests"]))


def chk_json(root, final):
    try:
        return json.loads((root / "config.json").read_text()).get("timeout") == 30
    except Exception:
        return False


TASKS = {
    "bugfix-careless": (fx_bugfix_careless, pol_bugfix_careless,
                        ["Tes test_stats gagal, tolong perbaiki stats.py."], lambda r, f: pytest_ok(r)),
    "bugfix-diligent": (fx_bugfix_diligent, pol_bugfix_diligent,
                        ["slugify salah, perbaiki sampai tesnya lulus."], lambda r, f: pytest_ok(r)),
    "syntax-slip": (fx_syntax_slip, pol_syntax_slip,
                    ["restock harus dibatasi MAX_STOCK (100). Tambahkan."], lambda r, f: pytest_ok(r)),
    "big-log": (fx_big_log, pol_big_log,
                ["Di app.log, berapa ERROR db-timeout antara jam 10:00 dan 10:59, dan request id pertamanya?"],
                chk_big_log),
    "refactor-5-files": (fx_refactor, pol_refactor,
                         ["Ganti nama get_user_name jadi fetch_display_name di seluruh proyek."],
                         lambda r, f: pytest_ok(r)),
    "refactor-10-files": (lambda r: fx_refactor(r, MODS10),
                          lambda st, wi, p, r: pol_refactor(st, wi, p, r, refactor_files(MODS10)),
                          ["Ganti nama get_user_name jadi fetch_display_name di seluruh proyek."],
                          lambda r, f: pytest_ok(r)),
    "long-session-28-tools": (fx_long_session, pol_long_session,
                              ["Audit repo ini: jumlah TODO per folder, modul terbesar, dan modul yang import requests."],
                              chk_long),
    "chat-3-turns-vault": (fx_chat_vault, pol_chat_vault,
                           ["Apa rencana rilis 1.4.6?", "Cek CHANGELOG.md, apa isi 1.4.6?",
                            "Ringkas catatan meeting relay."], lambda r, f: True),
    "json-config": (fx_json_config, pol_json_config,
                    ["Tambahkan timeout: 30 ke config.json."], chk_json),
}


# ------------------------------------------------------------------ run one -----

def run_one(task: str, mode: str) -> dict:
    base = RUNS / f"{task}--{mode}"
    if base.exists():
        shutil.rmtree(base)
    root, home = base / "proj", base / "home"
    root.mkdir(parents=True)
    os.environ.update({"NEOVARCH_HOME": str(home), "NEOVARCH_9ROUTER_SUPERVISE": "0",
                       "NEOVARCH_9ROUTER_AUTOSTART": "0", "NEOVARCH_9ROUTER_URL": "http://127.0.0.1:9/v1",
                       "NEOVARCH_9ROUTER_DATA_DIR": str(base / "no9r"), "NEOVARCH_9ROUTER_BIN": str(base / "no9r/x"),
                       "NEOVARCH_API_KEY": "bench"})
    fixture, policy, prompts, check = TASKS[task]
    fixture(root)
    from neovarch.paths import ensure_home
    ensure_home()
    from neovarch import config as cfgmod
    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "bench-model", "base_url": "http://127.0.0.1:9/v1",
                    "context_length": 128000}
    cfg["approvals"] = {"mode": "off"}
    cfg.setdefault("agent", {})["max_turns"] = 60
    cfg["timezone"] = "Asia/Jakarta"
    if mode != "legacy":
        cfg["agent"]["harness_mode"] = "tempa"
        cfg["agent"]["tempa_profile"] = "tinggi" if mode == "tempa-tinggi" else "ringan"
        if mode == "tempa-nomask":
            cfg["agent"]["tempa_mask"] = False
    vault = base / "proj-vault"
    if vault.exists():
        cfg["memory"] = {"obsidian_vault": str(vault), "obsidian_enabled": True}
    cfgmod.save_config(cfg)

    import neovarch.agent as agentmod
    from neovarch.agent import Agent
    from neovarch.llm import Completion
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext

    calls: list[dict] = []
    state: dict = {}
    helper = P()
    prev = [None]

    async def fake_stream_chat(*, base_url, api_key, model, messages, tools=None, on_text=None,
                               on_reasoning=None, **_kw):
        chunks = serialize(tools or [], messages)
        toks = [ntok(c) + 4 for c in chunks]
        total = sum(toks)
        # cached prefix: leading chunks identical to the previous call (OpenAI-style, >=1024, 128-token steps)
        cached = 0
        if prev[0] is not None:
            for a, b, t in zip(prev[0], chunks, toks):
                if a != b:
                    break
                cached += t
        cached = (cached // 128) * 128 if cached >= 1024 else 0
        prev[0] = chunks
        text, tcs = policy(state, messages, helper, root)
        out_tok = ntok(text) + sum(ntok(c.arguments) + 8 for c in tcs)
        calls.append({"input": total, "cached": cached, "output": out_tok,
                      "tool_msgs_tokens": sum(t for t, m in zip(toks[1:], messages) if m["role"] == "tool")})
        if text and on_text:
            on_text(text)
        return Completion(text=text, tool_calls=tcs, usage={"prompt_tokens": total, "completion_tokens": out_tok})

    agentmod.stream_chat = fake_stream_chat
    store = SessionStore()
    rec = store.create(cwd=str(root))
    events: list = []

    async def approve(*_a):
        return "once"

    agent = Agent(rec, store, ToolContext(cwd=root, approve=approve), lambda k, pl: events.append((k, pl)))
    t0 = time.monotonic()
    finals = []

    async def go():
        for q in prompts:
            finals.append(await agent.run_turn(q))
    asyncio.run(go())
    wall = time.monotonic() - t0
    final = finals[-1] if finals else ""
    passed = bool(check(root, final))
    tin = sum(c["input"] for c in calls)
    tcached = sum(c["cached"] for c in calls)
    tout = sum(c["output"] for c in calls)
    errors = [pl.get("message") for k, pl in events if k == "error"]
    return {
        "task": task, "mode": mode, "turns": len(calls), "input_tokens": tin, "cached_tokens": tcached,
        "output_tokens": tout, "peak_context": max(c["input"] for c in calls),
        "wall_s": round(wall, 2), "passed": passed,
        "cost_nocache_usd": (tin * PRICE_IN + tout * PRICE_OUT) / 1e6,
        "cost_cache_usd": ((tin - tcached) * PRICE_IN + tcached * PRICE_CACHED + tout * PRICE_OUT) / 1e6,
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "rereads": state.get("rereads", 0), "errors": errors, "final": final[:300],
        "per_call_input": [c["input"] for c in calls],
    }


def main() -> None:
    if sys.argv[1] == "run":
        print(json.dumps(run_one(sys.argv[2], sys.argv[3])))
        return
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else RUNS / "results.json"
    results = []
    for task in TASKS:
        for mode in MODES:
            r = subprocess.run([sys.executable, __file__, "run", task, mode], capture_output=True, text=True,
                               timeout=600)
            line = (r.stdout.strip().splitlines() or [""])[-1]
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                results.append({"task": task, "mode": mode, "crash": (r.stderr or r.stdout)[-2000:]})
            print(task, mode, "ok" if "crash" not in results[-1] else "CRASH", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"tokenizer": TOKENIZER, "results": results}, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
