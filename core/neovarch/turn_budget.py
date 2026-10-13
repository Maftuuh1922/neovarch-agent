"""When a turn stops, and how the stop is explained (v1.4.7).

Before 1.4.7 a turn stopped hard after ``agent.max_turns`` model calls (30 by
default), mid-job, with the raw text "stopped after 30 model calls" which the
phone labelled "Model / endpoint". Long tool-driven jobs (PPT decks, reports)
hit it routinely, and typing "lanjutkan" hit it again 30 calls later.

Now the main stop conditions are about *progress*, not a count:

* loop: the same tool with the same arguments returned the same result
  ``LOOP_REPEATS`` times in this turn;
* no progress: ``NO_PROGRESS_FAILS`` tool calls failed in a row;
* budget: wall time (``agent.max_turn_minutes``) or tokens
  (``agent.max_turn_tokens``) for this turn.

``agent.max_turns`` is a *checkpoint*: when it is reached and the last segment
made progress (a new successful tool call), the turn continues silently with a
fresh segment, up to the hard ceiling ``agent.max_turn_steps``. A segment with
no new successful work stops with ``step_limit`` and a Lanjutkan action.

Every stop carries a code; :func:`describe` turns it into the plain-Indonesian
title / explanation / one-tap action shown identically on desktop and phone.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field

DEFAULT_CHECKPOINT = 150      # agent.max_turns (older configs carry 30: still a checkpoint, never a hard stop)
DEFAULT_HARD_STEPS = 600      # agent.max_turn_steps
DEFAULT_MINUTES = 90          # agent.max_turn_minutes
DEFAULT_TOKENS = 4_000_000    # agent.max_turn_tokens (prompt + completion, summed over calls)
LOOP_REPEATS = 5
NO_PROGRESS_FAILS = 12
# Diminishing returns: after this many web calls in one turn the model is told (once) to answer with what
# it has; after STALL_CALLS tool calls in a row that found nothing new, the same nudge.
WEB_NUDGE_CALLS = 8
STALL_CALLS = 6
WEB_TOOLS = ("web_search", "web_fetch")
NUDGE_TEXT = ("[Tempest] Pencarian sudah {n} kali dan hasil baru makin sedikit. Jawab sekarang dari sumber yang sudah "
              "diambil (sebut URL-nya); bagian yang tidak ditemukan katakan terus terang. Cari lagi hanya bila benar-"
              "benar ada petunjuk baru yang spesifik.")

# One-tap actions the clients render as a button (same labels everywhere).
ACTIONS = {
    "continue": "Lanjutkan",
    "retry": "Coba lagi",
    "switch_model": "Ganti model",
    "settings": "Buka pengaturan",
}

CONTINUE_WORDS = {"lanjutkan", "lanjut", "teruskan", "continue", "lanjutkan saja", "lanjutkan dari terakhir"}
CONTINUE_NOTE = ("[Lanjutan] Giliran sebelumnya berhenti di tengah pekerjaan. Lanjutkan pekerjaan yang sama dari "
                 "titik terakhir: periksa file/hasil yang sudah ada, jangan ulangi langkah yang sudah selesai, lalu "
                 "selesaikan sisanya.")


def _num(cfg_get, key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(cfg_get(key, default) or default)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _sig(name: str, args: dict) -> str:
    try:
        raw = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raw = str(args)
    return name + ":" + hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16]


@dataclass
class TurnBudget:
    checkpoint: int = DEFAULT_CHECKPOINT
    hard_steps: int = DEFAULT_HARD_STEPS
    max_seconds: float = DEFAULT_MINUTES * 60
    max_tokens: int = DEFAULT_TOKENS
    clock: object = time.monotonic
    steps: int = 0
    tokens: int = 0
    segments: int = 1
    started: float = 0.0
    _seen_ok: set = field(default_factory=set)
    _repeats: dict = field(default_factory=dict)
    _segment_progress: bool = False
    _fails: int = 0
    loop_tool: str = ""
    extended: int = 0          # how often the checkpoint was extended (made visible, never silent)
    web_calls: int = 0
    _stall: int = 0
    _nudged: bool = False
    _announce: bool = False

    @classmethod
    def from_config(cls, cfg_get, clock=time.monotonic) -> "TurnBudget":
        b = cls(checkpoint=_num(cfg_get, "agent.max_turns", DEFAULT_CHECKPOINT, 1, 1000),
                hard_steps=_num(cfg_get, "agent.max_turn_steps", DEFAULT_HARD_STEPS, 10, 5000),
                max_seconds=60 * _num(cfg_get, "agent.max_turn_minutes", DEFAULT_MINUTES, 1, 24 * 60),
                max_tokens=_num(cfg_get, "agent.max_turn_tokens", DEFAULT_TOKENS, 10_000, 100_000_000),
                clock=clock)
        b.hard_steps = max(b.hard_steps, b.checkpoint)
        b.started = clock()
        return b

    @property
    def limit(self) -> int:
        """The number shown as "langkah n/limit": the current segment's checkpoint, capped by the ceiling."""
        return min(self.hard_steps, self.checkpoint * self.segments)

    def before_call(self) -> str | None:
        """None to make the next model call, else the stop code."""
        if self.steps >= self.hard_steps:
            return "step_limit"
        if self.clock() - self.started >= self.max_seconds:
            return "budget_time"
        if self.tokens >= self.max_tokens:
            return "budget_tokens"
        if self.steps >= self.checkpoint * self.segments:
            if not self._segment_progress:
                return "step_limit"
            self.segments += 1          # still making progress: extend, and say so (see take_extension)
            self._segment_progress = False
            self.extended += 1
            self._announce = True
        self.steps += 1
        return None

    def take_extension(self) -> str | None:
        """A one-line notice when the last :meth:`before_call` extended the step limit (else None).

        The counter shown as ``langkah n/limit`` never runs past its limit: the limit grows first, and the
        user sees why."""
        if not self._announce:
            return None
        self._announce = False
        return (f"Batas langkah diperpanjang ke {self.limit} (langkah {self.steps}): masih ada kemajuan. "
                f"Batas keras {self.hard_steps}.")

    def nudge(self) -> str | None:
        """Diminishing returns: one hidden 'answer now' note, or None."""
        if self._nudged:
            return None
        if self.web_calls >= WEB_NUDGE_CALLS or (self.web_calls >= 3 and self._stall >= STALL_CALLS):
            self._nudged = True
            return NUDGE_TEXT.format(n=self.web_calls)
        return None

    def add_usage(self, usage: dict | None) -> None:
        from neovarch.usage_stats import normalize
        n = normalize(usage) or {}
        self.tokens += int(n.get("input") or 0) + int(n.get("output") or 0)

    def record_tool(self, name: str, args: dict, result: str, ok: bool) -> str | None:
        """Track one tool call; returns ``loop`` / ``no_progress`` when the turn must stop."""
        sig = _sig(name, args)
        rsig = sig + ":" + hashlib.sha1((result or "")[:4000].encode("utf-8", "replace")).hexdigest()[:12]
        self._repeats[rsig] = self._repeats.get(rsig, 0) + 1
        if name in WEB_TOOLS:
            self.web_calls += 1
        if ok:
            self._fails = 0
            if sig not in self._seen_ok:
                self._seen_ok.add(sig)
                self._segment_progress = True
                self._stall = 0
            else:
                self._stall += 1
        else:
            self._fails += 1
            self._stall += 1
        if self._repeats[rsig] >= LOOP_REPEATS:
            self.loop_tool = name
            return "loop"
        if self._fails >= NO_PROGRESS_FAILS:
            return "no_progress"
        return None

    def progress_payload(self) -> dict:
        limit = max(self.limit, self.steps)  # never "9/3": the limit is extended before a step passes it
        return {"step": self.steps, "limit": limit, "max": self.hard_steps, "extended": self.extended}


def is_continue(text: str) -> bool:
    t = re.sub(r"[\s.!…]+$", "", (text or "").strip().lower())
    return t in CONTINUE_WORDS


def classify_llm_error(msg: str) -> str:
    m = (msg or "").lower()
    if "401" in m or "403" in m or "api key" in m or "unauthorized" in m or "kunci api" in m:
        return "auth"
    if "402" in m or "credit" in m or "billing" in m or "quota" in m or "kuota" in m:
        return "quota"
    if "429" in m or "rate limit" in m or "dibatasi" in m or "freeusagelimit" in m:
        return "rate_limit"
    if "could not reach" in m or "timed out" in m or "timeout" in m or "connection" in m or "belum berjalan" in m:
        return "connection"
    if "context" in m and ("length" in m or "too long" in m or "maximum" in m):
        return "context"
    return "model"


_TEXT = {
    "step_limit": ("Batas langkah tercapai",
                   "Agen sudah bekerja {steps} langkah di giliran ini tanpa kemajuan baru, jadi berhenti agar tidak "
                   "boros. Semua yang sudah dibuat tetap tersimpan. Tekan Lanjutkan untuk meneruskan dari titik terakhir.",
                   "continue"),
    "budget_time": ("Batas waktu giliran tercapai",
                    "Giliran ini sudah berjalan {minutes} menit. Hasil yang sudah ada tetap tersimpan. Tekan Lanjutkan "
                    "untuk meneruskan, atau naikkan batasnya di Pengaturan › Agen.",
                    "continue"),
    "budget_tokens": ("Batas token giliran tercapai",
                      "Giliran ini sudah memakai {tokens} token. Hasil yang sudah ada tetap tersimpan. Tekan Lanjutkan "
                      "untuk meneruskan, atau naikkan batasnya di Pengaturan › Agen.",
                      "continue"),
    "loop": ("Agen berputar di langkah yang sama",
             "Agen mengulang {tool} dengan hasil yang sama, jadi dihentikan. Coba lagi dengan arahan yang lebih "
             "spesifik, atau ganti model.",
             "retry"),
    "no_progress": ("Agen buntu",
                    "{fails} langkah terakhir gagal berturut-turut. Coba ganti model, atau beri arahan yang lebih jelas.",
                    "switch_model"),
    "auth": ("Kunci API ditolak",
             "Penyedia model menolak kunci API. Periksa kunci di Pengaturan › Model.",
             "settings"),
    "quota": ("Kuota atau saldo penyedia habis",
              "Penyedia model menolak karena kuota/saldo habis. Isi saldo atau ganti model.",
              "switch_model"),
    "rate_limit": ("Penyedia sedang membatasi",
                   "Terlalu banyak permintaan ke model ini. Tunggu sebentar lalu coba lagi, atau ganti model.",
                   "retry"),
    "connection": ("Penyedia model tidak terjangkau",
                   "PC tidak bisa menghubungi penyedia model (internet atau endpoint mati). Periksa koneksi lalu coba lagi.",
                   "retry"),
    "context": ("Percakapan terlalu panjang untuk model ini",
                "Konteks melebihi batas model. Mulai sesi baru atau pilih model dengan konteks lebih besar.",
                "switch_model"),
    "model": ("Model atau penyedia bermasalah",
              "Model mengembalikan galat. Coba lagi, atau ganti model.",
              "switch_model"),
    "verification": ("Verifikasi gagal",
                     "Perubahan kode tidak lolos tes/verifikasi. Detailnya ada di jawaban agen.",
                     "retry"),
    "tool": ("Alat gagal",
             "Sebuah alat gagal dijalankan. Coba lagi.",
             "retry"),
}


def describe(code: str, *, steps: int = 0, seconds: float = 0, tokens: int = 0, tool: str = "",
             fails: int = 0, detail: str = "") -> dict:
    """Payload for the ``error`` event: code, title, message, action (+label), detail.

    ``message`` keeps the old field meaning (one human sentence), so older clients
    that only show ``message`` get the plain explanation, never an internal string."""
    title, text, action = _TEXT.get(code, _TEXT["model"])
    msg = text.format(steps=steps, minutes=max(1, int(seconds // 60)), tokens=f"{tokens:,}".replace(",", "."),
                      tool=tool or "alat yang sama", fails=fails or NO_PROGRESS_FAILS)
    if detail and code in ("model", "rate_limit", "connection", "auth", "quota") and detail != msg:
        # A provider-specific Indonesian explanation (9Router etc.) is more useful than the generic text.
        if not re.search(r"[A-Za-z]+Error|Traceback|HTTP \d{3}: \{", detail) and len(detail) < 400:
            msg = detail
    return {"code": code, "title": title, "message": msg, "action": action, "action_label": ACTIONS[action],
            **({"detail": detail[:600]} if detail else {})}
