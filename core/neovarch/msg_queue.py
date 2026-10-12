"""Per-session message queue (v1.4.7): messages sent while a turn runs wait here.

The queue lives on the session record (``rec["queue"]``) so every client (phone,
desktop) sees the same list and it survives a gateway restart. The gateway
drains it in order when a turn ends; a turn stopped by the person or by an
error *pauses* the queue (``rec["queue_paused"]``) instead of firing the next
message into a broken state. "Kirim sekarang" moves an item to the front and
interrupts the running turn so it goes next.

Item: ``{"id": "q-…", "text": str, "attachments": [upload meta…], "ts": float}``.
Pure functions over the record; the gateway saves and broadcasts.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

MAX_ITEMS = 20
MAX_TEXT = 20000


class QueueError(ValueError):
    """A queue request that cannot be honoured (unknown id, empty text, full)."""


def items(rec: dict) -> list[dict]:
    q = rec.get("queue")
    if not isinstance(q, list):
        q = []
    # Older cores kept steered texts in rec["queued"] (plain strings): fold them in once.
    legacy = rec.pop("queued", None)
    if isinstance(legacy, list):
        for t in legacy:
            if str(t or "").strip():
                q.append(_item(str(t), []))
    rec["queue"] = q
    return q


def _item(text: str, attachments: list[dict] | None) -> dict:
    return {"id": "q-" + secrets.token_hex(4), "text": text[:MAX_TEXT], "attachments": list(attachments or []),
            "ts": time.time()}


def push(rec: dict, text: str, attachments: list[dict] | None = None) -> dict:
    text = str(text or "")
    if not text.strip() and not attachments:
        raise QueueError("text is required")
    q = items(rec)
    if len(q) >= MAX_ITEMS:
        raise QueueError(f"antrean penuh (maks {MAX_ITEMS} pesan)")
    it = _item(text, attachments)
    q.append(it)
    return it


def _find(rec: dict, qid: str) -> int:
    for i, it in enumerate(items(rec)):
        if it.get("id") == qid:
            return i
    raise QueueError(f"pesan antrean tidak ditemukan: {qid}")


def edit(rec: dict, qid: str, text: str) -> dict:
    q = items(rec)
    i = _find(rec, qid)
    if not str(text or "").strip() and not q[i].get("attachments"):
        raise QueueError("text is required")
    q[i]["text"] = str(text)[:MAX_TEXT]
    return q[i]


def remove(rec: dict, qid: str) -> dict:
    q = items(rec)
    return q.pop(_find(rec, qid))


def to_front(rec: dict, qid: str) -> dict:
    q = items(rec)
    it = q.pop(_find(rec, qid))
    q.insert(0, it)
    return it


def pop_next(rec: dict) -> dict | None:
    q = items(rec)
    return q.pop(0) if q else None


def clear(rec: dict) -> int:
    n = len(items(rec))
    rec["queue"] = []
    rec.pop("queue_paused", None)
    return n


def paused(rec: dict) -> bool:
    return bool(rec.get("queue_paused")) and bool(items(rec))


def set_paused(rec: dict, value: bool, reason: str = "") -> None:
    if value and items(rec):
        rec["queue_paused"] = {"reason": reason or "stopped", "ts": time.time()}
    else:
        rec.pop("queue_paused", None)


def payload(rec: dict, public=None) -> dict[str, Any]:
    """What clients get in ``queue.update`` / ``queue.list`` / session.resume."""
    pub = public or (lambda m: m)
    q = items(rec)
    p = rec.get("queue_paused") if q else None
    return {"items": [{"id": it["id"], "text": it.get("text") or "", "ts": it.get("ts"),
                       "attachments": [pub(a) for a in it.get("attachments") or []]} for it in q],
            "count": len(q), "paused": bool(p),
            **({"paused_reason": p.get("reason")} if isinstance(p, dict) else {})}
