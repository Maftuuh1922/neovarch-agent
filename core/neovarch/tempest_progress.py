"""Tempest progress artefact + todo recitation.

The model keeps a plan with the ``update_plan`` tool (the whole list each time: id, text,
status todo/doing/done, optional note). It is stored per project under
``~/.neovarch/progress/<hash of the project path>.json`` (plus a readable ``.md`` next to it),
never inside the user's repository.

* A new chat in a project with an unfinished plan gets that plan recited once on its first
  user message (stored with the message, so the prefix stays stable): work cut by a reset
  continues where it stopped instead of being redone.
* In long sessions the current plan is recited at the end of the context on every call
  (an ephemeral trailing note after the newest message; earlier messages never change, so
  caches keep hitting) - the model re-reads its goals instead of drifting.
* "done" is the model's claim; the verify gate decides ``verified``: items marked done
  when the tests pass are verified, a failed gate marks them unverified.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

PLAN_MARK = "# Rencana & progres"
STATUSES = ("todo", "doing", "done")
SCHEMA = {
    "type": "function",
    "function": {
        "name": "update_plan",
        "description": ("Simpan rencana kerja dan progresnya (daftar lengkap setiap kali). Pakai untuk tugas "
                        "panjang/berlangkah banyak: status todo/doing/done, plus catatan temuan penting. "
                        "Rencana dibacakan ulang otomatis di sesi berikutnya dan di akhir konteks."),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "text": {"type": "string"},
                                   "status": {"type": "string", "enum": list(STATUSES)}},
                    "required": ["id", "text", "status"]}},
                "note": {"type": "string", "description": "temuan/keputusan singkat (opsional)"},
            },
            "required": ["items"],
        },
    },
}


class Progress:
    def __init__(self, work: Path, home: Path):
        self.work = Path(work).resolve()
        key = hashlib.sha1(str(self.work).encode("utf-8")).hexdigest()[:16]
        self.path = Path(home) / "progress" / f"{key}.json"

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data["cwd"] = str(self.work)
        data["updated"] = time.time()
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        self.path.with_suffix(".md").write_text(render(data, header=f"{PLAN_MARK} — {self.work}") + "\n",
                                                encoding="utf-8")

    def update(self, args: dict, session_id: str = "") -> str:
        raw = args.get("items")
        if not isinstance(raw, list) or not raw:
            return "error: items (daftar {id, text, status}) wajib diisi"
        old = {str(i.get("id")): i for i in self.load().get("items") or []}
        items = []
        for i, it in enumerate(raw[:50]):
            if not isinstance(it, dict):
                continue
            iid = str(it.get("id") or i + 1)[:60]
            status = str(it.get("status") or "todo").lower()
            status = status if status in STATUSES else "todo"
            prev = old.get(iid) or {}
            item = {"id": iid, "text": str(it.get("text") or "")[:300], "status": status}
            if status == "done" and prev.get("status") == "done" and "verified" in prev:
                item["verified"] = prev["verified"]
            items.append(item)
        data = self.load()
        data["items"] = items
        data["session"] = session_id
        note = str(args.get("note") or "").strip()
        if note:
            data["notes"] = (list(data.get("notes") or []) + [note[:400]])[-10:]
        self.save(data)
        done = sum(1 for i in items if i["status"] == "done")
        return f"plan diperbarui: {len(items)} item, {done} selesai"

    def mark_verified(self, ok: bool) -> None:
        data = self.load()
        items = data.get("items") or []
        changed = False
        for it in items:
            if it.get("status") == "done" and it.get("verified") is not ok:
                it["verified"] = ok
                changed = True
        if changed:
            self.save(data)

    def unfinished(self) -> bool:
        items = self.load().get("items") or []
        return any(i.get("status") != "done" for i in items)


def render(data: dict, header: str = PLAN_MARK) -> str:
    items = data.get("items") or []
    if not items:
        return ""
    lines = [header]
    for it in items:
        box = {"done": "[x]", "doing": "[~]"}.get(it.get("status"), "[ ]")
        flag = ""
        if it.get("status") == "done" and it.get("verified") is True:
            flag = " (terverifikasi)"
        elif it.get("status") == "done" and it.get("verified") is False:
            flag = " (belum terverifikasi: tes gagal)"
        lines.append(f"- {box} {it.get('id')}: {it.get('text')}{flag}")
    for n in (data.get("notes") or [])[-5:]:
        lines.append(f"Catatan: {n}")
    return "\n".join(lines)


def session_start_note(prog: Progress) -> str:
    """Recited once on the first message of a new chat when the project has an unfinished plan."""
    data = prog.load()
    if not data.get("items") or not prog.unfinished():
        return ""
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(data.get("updated") or time.time()))
    return render(data, header=f"{PLAN_MARK} (dari sesi sebelumnya, {when}; lanjutkan dari sini, "
                               "jangan ulangi yang sudah [x])")


def recitation(prog: Progress) -> str:
    data = prog.load()
    body = render(data, header=f"{PLAN_MARK} (pengingat otomatis dari harness — bukan pesan pengguna)")
    return body
