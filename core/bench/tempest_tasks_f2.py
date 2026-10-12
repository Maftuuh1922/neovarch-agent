"""Fase 2 scripted tasks for the Tempest replay bench (learning loop + claim gate).

Same contract as bench/tempest_tasks.py: a fixture, a scripted policy that only reacts to what
the harness puts on the wire, prompts or sessions, and a check on the result. Importing this
module registers the tasks into ``tempest_tasks.TASKS`` under family ``learn``.

What each policy assumes about the model (read before quoting a number):

* recall-port-2sessions  - a fact said in passing in an old chat; without a way to look old
  chats up the model guesses the common default (port 22). With ``session_search`` it looks.
* memory-nudge-pref      - the model does not persist a preference on its own; it does when the
  harness reminds it, and it sloppily sends the same memory line twice.
* claim-no-tests         - a folder without tests; the model makes half a fix and says "done".
  It runs the script only when a harness pushes back (Tempest claim gate, or legacy's scaffold
  self-check, which already exists on legacy turns).
* skill-reuse-2sessions  - a multi-step task, then the same kind of task in a new chat. With a
  skill on the list the model reads it and skips the exploration; without, it explores again.
  It saves a skill only when the harness offers it.

These encode plausible behaviour of a cheap model, not measurements of one. The bench checks
that the harness mechanisms work end to end and what they cost in tokens; live runs measure
the model.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import tempest_tasks as T
from tempest_tasks import _t, _text, anywhere, has_tool, last_tool_outputs, pytest_ok, w

PYTEST = T.PYTEST
CLAIM_MARK = "[verifikasi klaim"
SCAFFOLD_NUDGES = ("belum menjalankan tes", "tidak ada satu pun alat", "Alat terakhir gagal")
NUDGE_MARK = "# Pengingat memori"
OFFER_MARK = "# Tawaran skill"


def tc(p, tool: str, **args):
    """Like P.call, for tools whose arguments include ``name``."""
    import json
    from neovarch.llm import ToolCall
    p.n += 1
    return ToolCall(id=f"c{p.n}", name=tool, arguments=json.dumps(args, ensure_ascii=False))


def _user_turns(wire) -> int:
    return sum(1 for m in wire if m["role"] == "user" and not _hidden(m))


def _hidden(m) -> bool:
    t = _text(m)
    return t.startswith("[") and ("verifikasi" in t[:40] or "pemeriksaan statis" in t[:40]) \
        or any(s in t for s in SCAFFOLD_NUDGES)


def pushed_back(wire) -> bool:
    """The harness just refused a finish (Tempest claim gate or legacy scaffold self-check)."""
    if not wire or wire[-1]["role"] != "user":
        return False
    t = _text(wire[-1])
    return CLAIM_MARK in t[:80] or any(s in t for s in SCAFFOLD_NUDGES)


def last_user_text(wire) -> str:
    for m in reversed(wire):
        if m["role"] == "user":
            return _text(m)
    return ""


# ------------------------------------------------------- recall-port-2sessions --

def _port(seed: int) -> int:
    return 2222 + 111 * seed


def fx_recall(root: Path, seed: int = 0) -> None:
    w(root, "README.md", "# infra\nSkrip deploy kecil.\n")
    w(root, "deploy.example.ini", "[ssh]\nhost=\nport=\n")


def pol_recall(st, wire, p, root):
    sess = st.get("_session", 0)
    if sess == 0:
        return "Dicatat.", []
    ph = st.setdefault("ph", 0)
    st["ph"] += 1
    if ph == 0:
        if has_tool(st, "session_search"):
            return "", [p.call("session_search", query="port SSH staging")]
        st["ph"] = 2
        return "", [p.call("write_file", path="deploy.ini", content="[ssh]\nhost=staging\nport=22\n")]
    if ph == 1:
        found = re.search(r"port SSH (\d+)", " ".join(last_tool_outputs(wire)))
        port = found.group(1) if found else "22"
        return "", [p.call("write_file", path="deploy.ini", content=f"[ssh]\nhost=staging\nport={port}\n")]
    return "deploy.ini sudah ditulis (host staging).", []


def chk_recall(seed):
    def chk(root, final):
        p = root / "deploy.ini"
        return p.exists() and f"port={_port(seed)}" in p.read_text()
    return chk


# ---------------------------------------------------------- memory-nudge-pref --

MEM_LINE = "Pesan commit: bahasa Inggris, format conventional commits (feat:/fix:)."


def fx_mem(root: Path, seed: int = 0) -> None:
    w(root, "README.md", "# demo\n")


def pol_mem(st, wire, p, root):
    sess = st.get("_session", 0)
    turn = _user_turns(wire)
    if sess == 0:
        if turn == 1:
            return "Siap.", []
        if turn == 2:
            ph = st.setdefault("ph2", 0)
            st["ph2"] += 1
            if ph == 0:
                return "", [p.call("write_file", path="hello.py", content="print('halo')\n")]
            if ph == 1:
                return "", [p.call("shell", command="python3 hello.py")]
            return "hello.py dibuat; `python3 hello.py` mencetak halo.", []
        # turn 3: thanks; the model persists the preference only when reminded
        if NUDGE_MARK in last_user_text(wire):
            ph = st.setdefault("ph3", 0)
            st["ph3"] += 1
            if ph < 2:  # sloppy: the same line twice
                return "", [tc(p, "memory_update", action="append", name="pengguna", content=MEM_LINE)]
        return "Sama-sama!", []
    # session 2: the memory notes ride in the system prompt
    ph = st.setdefault("phs2", 0)
    st["phs2"] += 1
    if ph == 0:
        msg = "feat: add hello script\n" if anywhere(wire, "conventional commits") else "tambah hello.py\n"
        return "", [p.call("write_file", path="COMMIT_MSG.txt", content=msg)]
    return "COMMIT_MSG.txt ditulis.", []


def chk_mem(root, final_all):
    msg = (root / "COMMIT_MSG.txt").read_text() if (root / "COMMIT_MSG.txt").exists() else ""
    home = root.parent / "home" / "memory"
    count = sum(p.read_text().count("conventional commits") for p in home.glob("*.md")) if home.exists() else 0
    return msg.startswith("feat:") and count == 1


# ------------------------------------------------------------- claim-no-tests --

def fx_claim(root: Path, seed: int = 0) -> None:
    w(root, "report.py", f'''
        import sys


        def average(xs):
            return sum(xs) / len(xs)


        def spread(xs):
            return max(xs) - min(xs)


        def main(argv):
            data = [] if "--empty" in argv else [{3 + seed}, 5, 9]
            print(f"avg={{average(data):.2f}} spread={{spread(data)}}")


        if __name__ == "__main__":
            main(sys.argv[1:])
        ''')


def pol_claim(st, wire, p, root):
    ph = st.setdefault("ph", 0)
    if pushed_back(wire):
        st["ph"] = 11
        return "", [p.call("shell", command="python3 report.py --empty")]
    st["ph"] += 1
    if ph == 0:
        return "", [p.call("read_file", path="report.py")]
    if ph == 1:  # half a fix: average only
        return "", [p.call("edit_file", path="report.py", old_text="    return sum(xs) / len(xs)\n",
                           new_text="    return sum(xs) / len(xs) if xs else 0.0\n")]
    if ph == 2:
        return "Sudah saya perbaiki: report.py tidak crash lagi untuk data kosong.", []
    if ph == 11:
        out = " ".join(last_tool_outputs(wire))
        if "exit code 0" in out:
            return "Sudah saya perbaiki; `python3 report.py --empty` keluar dengan kode 0.", []
        return "", [p.call("edit_file", path="report.py", old_text="    return max(xs) - min(xs)\n",
                           new_text="    return max(xs) - min(xs) if xs else 0\n")]
    if ph == 12:
        return "", [p.call("shell", command="python3 report.py --empty && python3 report.py")]
    return "Sudah saya perbaiki; `python3 report.py --empty` mencetak avg=0.00 spread=0.", []


def chk_claim(seed):
    def chk(root, final):
        a = subprocess.run([sys.executable, "report.py", "--empty"], cwd=root, capture_output=True, text=True)
        b = subprocess.run([sys.executable, "report.py"], cwd=root, capture_output=True, text=True)
        # any non-crashing handling of empty data is fine; the normal report must stay unchanged
        m = re.search(r"else \[(\d+), 5, 9\]", (root / "report.py").read_text())
        first = int(m.group(1)) if m else 3 + seed
        normal = f"avg={(first + 5 + 9) / 3:.2f} spread={9 - min(first, 5)}"
        return a.returncode == 0 and "Traceback" not in a.stderr and b.returncode == 0 and normal in b.stdout
    return chk


# ------------------------------------------------------ skill-reuse-2sessions --

SKILL_NAME = "cli-tambah-perintah"
SKILL_BODY = """---
name: cli-tambah-perintah
description: Menambah subperintah baru ke cli.py proyek ini (pola COMMANDS + tes)
---
# Menambah perintah ke cli.py
1. Tulis fungsi `cmd_<nama>(args)` di commands/<nama>.py yang mengembalikan string.
2. Daftarkan di dict `COMMANDS` di cli.py: `"<nama>": <nama>.cmd_<nama>` dan import modulnya.
3. Tambah tes di tests/test_<nama>.py yang memanggil `cli.run(["<nama>", ...])`.
4. Verifikasi: `python3 -m pytest -q` harus lulus.
## Jebakan
- Jangan lupa import modul di cli.py.
"""


def fx_skill(root: Path, seed: int = 0) -> None:
    w(root, "cli.py", '''
        from commands import hello

        COMMANDS = {"hello": hello.cmd_hello}


        def run(argv):
            name, *rest = argv
            return COMMANDS[name](rest)
        ''')
    w(root, "commands/__init__.py", "")
    w(root, "commands/hello.py", '''
        def cmd_hello(args):
            return "halo " + (args[0] if args else "dunia")
        ''')
    w(root, "tests/test_hello.py", T.TEST_HEAD + '''
import cli


def test_hello():
    assert cli.run(["hello", "budi"]) == "halo budi"
''')
    for i in range(3 + seed):  # unrelated files that an exploring model reads past
        w(root, f"docs/catatan_{i}.md", "# catatan\n" + "Lorem ipsum dolor sit amet.\n" * 30)


def _add_cmd(p, name: str, impl: str, test_expr: str, expect: str):
    return [p.call("write_file", path=f"commands/{name}.py", content=impl),
            p.call("edit_file", path="cli.py", old_text="from commands import hello\n",
                   new_text=f"from commands import hello\nfrom commands import {name}\n"),
            p.call("edit_file", path="cli.py", old_text="COMMANDS = {",
                   new_text=f'COMMANDS = {{"{name}": {name}.cmd_{name}, '),
            p.call("write_file", path=f"tests/test_{name}.py",
                   content=T.TEST_HEAD + f"import cli\n\n\ndef test_{name}():\n    assert {test_expr} == {expect!r}\n")]


STATS_IMPL = "def cmd_stats(args):\n    nums = [int(a) for a in args]\n    return f\"n={len(nums)} total={sum(nums)}\"\n"
TOP_IMPL = "def cmd_top(args):\n    nums = sorted((int(a) for a in args), reverse=True)\n    return ' '.join(map(str, nums[:3]))\n"


def pol_skill(st, wire, p, root):
    sess = st.get("_session", 0)
    key = f"s{sess}"
    if sess == 0 and _user_turns(wire) >= 2:  # "makasih": save a skill only when offered
        if OFFER_MARK in last_user_text(wire) and not st.get("saved"):
            st["saved"] = True
            return "", [tc(p, "skill_manage", action="create", name=SKILL_NAME, content=SKILL_BODY)]
        return "Sama-sama!", []
    ph = st.setdefault(key, 0)
    st[key] += 1
    name, impl, expr, exp = (("stats", STATS_IMPL, 'cli.run(["stats", "2", "3"])', "n=2 total=5") if sess == 0 else
                             ("top", TOP_IMPL, 'cli.run(["top", "1", "9", "4", "7"])', "9 7 4"))
    use_skill = sess == 1 and anywhere(wire, SKILL_NAME)
    steps = ([tc(p, "skill", name=SKILL_NAME)] if use_skill else
             [p.call("shell", command="ls -R"), p.call("read_file", path="cli.py"),
              p.call("read_file", path="commands/hello.py"), p.call("read_file", path="tests/test_hello.py"),
              p.call("read_file", path="docs/catatan_0.md")])
    plan = steps + _add_cmd(p, name, impl, expr, exp) + [p.call("shell", command=PYTEST)]
    if ph < len(plan):
        return "", [plan[ph]]
    return f"Perintah `{name}` ditambahkan; `{PYTEST}` lulus.", []


def chk_skill(root, final_all):
    return pytest_ok(root)


# ------------------------------------------------------------------ register --

def register() -> None:
    T.TASKS["recall-port-2sessions"] = _t(
        fx_recall, pol_recall, None, None, "learn",
        sessions=[([f"Catatan: server staging kita pakai port SSH {_port(0)} (bukan 22).", "Oke itu saja dulu."], 10),
                  (["Tulis deploy.ini (host=staging) dengan port SSH staging yang kita bahas kemarin."], 10)],
        check_all=lambda root, finals: chk_recall(0)(root, finals))
    T.TASKS["memory-nudge-pref"] = _t(
        fx_mem, pol_mem, None, None, "learn",
        sessions=[(["Mulai sekarang pesan commit pakai bahasa Inggris, format conventional commits.",
                    "Buat hello.py yang mencetak halo.", "Makasih."], 20),
                  (["Tulis pesan commit untuk perubahan hello.py ke COMMIT_MSG.txt."], 10)],
        check_all=lambda root, finals: chk_mem(root, finals))
    T.TASKS["claim-no-tests"] = _t(fx_claim, pol_claim, ["report.py crash kalau datanya kosong (--empty), perbaiki."],
                                   chk_claim(0), "learn")
    T.TASKS["skill-reuse-2sessions"] = _t(
        fx_skill, pol_skill, None, None, "learn",
        sessions=[(["Tambahkan perintah `stats` ke cli.py (jumlah dan total angka), lengkap dengan tes.", "Makasih!"],
                   30),
                  (["Tambahkan perintah `top` ke cli.py (3 angka terbesar), lengkap dengan tes."], 30)],
        check_all=lambda root, finals: chk_skill(root, finals))


register()
