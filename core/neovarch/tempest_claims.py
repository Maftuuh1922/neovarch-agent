"""Tempest claim gate: a "done / fixed / tests pass" answer needs execution evidence.

The verify gate (tempest.py) already runs the project's test command when it can find one.
This gate covers the rest, deterministically and without extra LLM calls:

* the turn changed code, there is no detectable test command (or it did not run), and the
  final answer claims the work is finished, but nothing was executed successfully *after the
  last edit* (a script, a test, a build: any shell command with exit code 0);
* the answer says tests pass, but no test command ran successfully in this turn and the
  harness did not verify it either;
* the answer claims success right after the last command failed.

On a problem the model gets one hidden correction (``kind: claim``, sharing the verify retry
budget). If it still cannot show evidence, the answer goes out with an explicit
"belum terverifikasi" note instead of a false claim, and the turn's ``verification`` status is
``unverified``.
"""

from __future__ import annotations

import re

from neovarch import scaffold

CLAIM_MARK = "[verifikasi klaim"
EXTRA_DONE = re.compile(
    r"(\b(sudah|telah)\s+(selesai|beres|jalan|berfungsi|bisa\s+dipakai)\b|\bsekarang\s+(sudah\s+)?(berfungsi|jalan|bekerja)\b"
    r"|\b(it|everything)\s+(now\s+)?works\b|\bworks\s+now\b|\b(is|are)\s+(now\s+)?fixed\b|\bdone\b[.!]?\s*$)",
    re.IGNORECASE | re.MULTILINE)
TESTS_PASS = re.compile(r"(\b(all|the)\s+tests\s+pass(ed)?\b|\bsemua\s+tes\s+lulus\b|\btes(nya)?\s+(sudah\s+)?lulus\b"
                        r"|\b\d+\s+passed\b)", re.IGNORECASE)
HONEST = re.compile(r"(belum\s+(saya\s+)?(tes|uji|verifikasi|dijalankan|diverifikasi)|not\s+(yet\s+)?(tested|verified|run)"
                    r"|tanpa\s+(tes|verifikasi)|belum\s+terverifikasi)", re.IGNORECASE)


def claims_done(text: str) -> bool:
    t = text or ""
    if HONEST.search(t):
        return False  # the model already says it is unverified: that is the honest answer
    return bool(scaffold.DONE_WORDS.search(t) or EXTRA_DONE.search(t) or TESTS_PASS.search(t))


def _exit_ok(t: dict) -> bool:
    return t.get("name") == "shell" and bool(t.get("ok"))


def evidence(ledger) -> dict:
    """What this turn actually executed, relative to its last edit."""
    last_write = max((i for i, t in enumerate(ledger.tools) if t["name"] in ("write_file", "edit_file") and t["ok"]),
                     default=-1)
    after = ledger.tools[last_write + 1:]
    ran_ok_after = [t for t in after if _exit_ok(t)]
    tests_ok = [t for t in ledger.tools if _exit_ok(t) and scaffold.TEST_CMD.search(str(t["args"].get("command") or ""))]
    shells = [i for i, t in enumerate(ledger.tools) if t["name"] == "shell"]
    last_shell = shells[-1] if shells else -1
    return {"last_write": last_write, "ran_after_edit": [str(t["args"].get("command") or "")[:160] for t in ran_ok_after],
            "tests_ok": bool(tests_ok),
            "last_shell_failed": bool(last_shell > last_write and not ledger.tools[last_shell]["ok"])}


def check(final_text: str, ledger, harness_verified: bool) -> str | None:
    """None when the answer may go out; otherwise the problem in one sentence."""
    if harness_verified or not claims_done(final_text):
        return None
    ev = evidence(ledger)
    if ev["last_shell_failed"] and not ev["ran_after_edit"]:
        return "Perintah terakhir yang kamu jalankan gagal, tapi jawabanmu menyatakan berhasil."
    if TESTS_PASS.search(final_text or "") and not ev["tests_ok"]:
        return "Jawabanmu menyebut tes lulus, tapi di giliran ini tidak ada perintah tes yang berhasil dijalankan."
    if ledger.code_changed() and not ev["ran_after_edit"]:
        changed = ", ".join(ledger.files_changed()[:5])
        return (f"Kamu mengubah kode ({changed}) dan menyatakan selesai, tapi tidak ada yang dijalankan setelah "
                "perubahan terakhir.")
    return None


def prompt(problem: str, attempt: int, retries: int) -> str:
    return (f"{CLAIM_MARK} — percobaan {attempt}/{retries}]\n{problem}\n"
            "Buktikan dulu: jalankan perintah yang menunjukkan hasilnya bekerja (tes, skrip, contoh pemakaian, build) "
            "dengan `shell`, perbaiki bila gagal, lalu jawab dengan output nyatanya. Kalau memang tidak bisa "
            "dijalankan di sini, katakan terus terang bahwa belum terverifikasi.")


def unverified_note(problem: str) -> str:
    return ("\n\n⚠️ Belum terverifikasi: " + problem + " Anggap hasil ini belum terbukti sampai dijalankan.")


def status(harness_verified: bool, verify_failed: bool, ledger, problem_left: bool) -> dict:
    """The turn's verification record for message.complete."""
    if verify_failed:
        return {"status": "failed"}
    if harness_verified:
        return {"status": "verified", "by": "harness"}
    if problem_left:
        return {"status": "unverified"}
    ev = evidence(ledger)
    if ledger.files_changed() and ev["ran_after_edit"]:
        return {"status": "verified", "by": "execution", "commands": ev["ran_after_edit"][-3:]}
    if ledger.files_changed():
        return {"status": "unverified" if ledger.code_changed() else "none"}
    return {"status": "none"}
