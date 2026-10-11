"""The agent loop: stream a completion, run the tools it asks for, repeat."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from neovarch import config as cfgmod
from neovarch import session_settings
from neovarch.llm import Completion, LLMError, stream_chat
from neovarch.store import SessionStore
from neovarch.tools import ToolContext, list_skills, run_tool, tool_schemas
from neovarch.logs import log as _log

EmitFn = Callable[[str, dict[str, Any]], Any]


# What the agent knows about the app it lives in. Without it a question like
# "can you see the Kantor?" sent the agent grepping app.asar and site-packages.
APP_KNOWLEDGE = """# About the Neovarch app you are running in
You are the agent inside Neovarch Agent: a desktop app (Windows/Linux) plus a phone remote app. The desktop
talks to this core (the `neovarch serve` gateway). Its pages, from the left rail:
- Obrolan / Sesi: chats with you; the session list has search, pinned chats and grouping.
- Kantor (Office): a 3D office where each running or recent chat and each Kanban task is an agent "employee"
  at a desk (status working / waiting-approval / idle, current task, model), with a live activity feed and a garden.
- Kanban: the task board (todo, ready, running, blocked, done) shared with the Kantor.
- Catatan / Obsidian: the user's Obsidian vault (tree, notes, backlinks, graph); it is also your long-term memory.
- Skill: installed skills (folders with SKILL.md under ~/.neovarch/skills).
- Artefak, Jadwal (cron jobs), Pasangkan HP (pair the phone remote by QR), Pengaturan (model, providers,
  custom OpenAI-compatible endpoints, appearance, security/approvals, memory).
Documents you can make on this PC (also when the request comes from the phone remote, since the phone only
relays chats to this PC): Word/PDF reports with `report_search` → `report_create` → `report_export`, and
PowerPoint decks (.pptx, "buatin PPT") with `ppt_setup` → the `ppt-master` skill → `ppt_export`.
Sending files to the user: the person may be chatting from the phone, which cannot open paths on this PC.
When they ask you to send/kirim/share a file, screenshot, image, report or deck ("kirim ke sini", "send it
here", "kasih screenshot-nya"), or when you finish a file they asked for, call `send_file` with its path:
images then show inline in their chat and other files as a download card, on the phone and the desktop.
A reply that only names a PC path does not deliver anything. Mention the path only as extra information.
How to answer questions about the app:
- Answer from this description directly. Call `office_status` to see the live Kantor (agents, status, tasks,
  active model); never search the filesystem, the app bundle (app.asar) or Python site-packages to learn
  what the app has.
- Use tools only when the request needs them. For exploration, stop and answer after at most 5 tool calls
  unless the task clearly needs more; prefer narrow commands with a short timeout over broad greps."""


def persona_prompt(session_id: str | None, office: dict | None) -> str:
    """Who answers a normal chat: always the main Neovarch Agent.

    Chats are not Kantor employees (before 1.4.6 every chat sat at a desk under
    a hashed staff name, so normal questions were answered "as Raka/Tegar/Ayu"
    and the Kantor was never empty). Employees exist only when the user asks the
    main agent to hire them; their own chats carry the company persona instead."""
    if not session_id:
        return ""
    lines = ["# Identitasmu\nKamu adalah **Neovarch Agent**, agen utama di PC ini. Kamu sendiri yang menjawab "
             "pengguna di obrolan ini; jangan mengaku sebagai pegawai Kantor.",
             "Kantor (Organisasi → Agency → Orang) kosong sampai pengguna memintamu mengisinya. Saat pengguna "
             "meminta membuat organisasi/agency, merekrut, memindah, memberhentikan pegawai, mengatur skill/alat/"
             "model/persona pegawai, atau memberi tugas, pakai alat `kantor`. Jangan merekrut pegawai tanpa diminta."]
    agents = [a for a in ((office or {}).get("agents") or []) if isinstance(a, dict)]
    if agents:
        lines.append(f"Pegawai Kantor saat ini: {len(agents)} orang; lihat detail dengan `kantor` aksi overview.")
    return "\n".join(lines)


def system_prompt(cfg: dict, cwd: Path, query: str = "", persona: str = "") -> str:
    parts = [cfgmod.soul_text().strip(), APP_KNOWLEDGE]
    if persona:
        parts.append(persona)
    extra = str(cfgmod.get_path(cfg, "agent.system_prompt", "") or "").strip()
    if extra:
        parts.append(extra)
    home = cfgmod.neovarch_home()
    notes = sorted((home / "memory").glob("*.md")) if (home / "memory").exists() else []
    if notes:
        mem = []
        for p in notes[:20]:
            text = p.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                mem.append(f"## {p.stem}\n{text[:4000]}")
        if mem:
            parts.append("# Memory notes (from earlier sessions)\n" + "\n\n".join(mem))
    parts.extend(_vault_prompt(cfg, query))
    skills = list_skills()
    if skills:
        parts.append("# Skills (read one with the `skill` tool before using it)\n"
                     + "\n".join(f"- {s['name']}: {s['description']}" for s in skills))
    parts.append(platform_prompt())
    parts.append(f"Current working directory: {cwd}\nDate: {now_text(cfg)}")
    return "\n\n".join(parts)


def platform_prompt(platform: str | None = None) -> str:
    """Which OS/shell the `shell` tool runs on, and how to take a screenshot there.

    Without it the agent wrote bash (ls, chromium, scrot) on Windows, where the
    shell tool runs cmd.exe, and screenshots of a page it built failed."""
    import sys
    plat = platform or sys.platform
    if plat == "win32":
        return ("# This PC\nOS: Windows. The `shell` tool runs cmd.exe (not bash): use `dir`, `type`, or "
                "`powershell -NoProfile -Command \"...\"`. Paths look like C:\\Users\\name\\...\n"
                "Screenshot of a web page or local HTML file: headless Edge or Chrome, e.g. "
                "`\"%ProgramFiles(x86)%\\Microsoft\\Edge\\Application\\msedge.exe\" --headless=new --disable-gpu "
                "--window-size=1280,800 --screenshot=C:\\path\\shot.png file:///C:/path/index.html` "
                "(or chrome.exe). Then deliver the PNG with `send_file`.")
    if plat == "darwin":
        return ("# This PC\nOS: macOS. The `shell` tool runs /bin/sh. Screenshot of a page: headless Chrome "
                "(`\"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome\" --headless=new "
                "--window-size=1280,800 --screenshot=/path/shot.png file:///path/index.html`); of the screen: "
                "`screencapture -x /path/shot.png`. Then deliver it with `send_file`.")
    return ("# This PC\nOS: Linux. The `shell` tool runs /bin/sh. Screenshot of a page or local HTML file: "
            "`chromium --headless=new --window-size=1280,800 --screenshot=/path/shot.png file:///path/index.html` "
            "(or google-chrome / chromium-browser); of the screen: `grim`, `gnome-screenshot -f` or `scrot`. "
            "Then deliver the PNG with `send_file`.")


def _vault_prompt(cfg: dict, query: str) -> list[str]:
    from neovarch import obsidian
    vault = obsidian.vault_path(cfg)
    if vault is None or not vault.is_dir():
        return []
    out = [f"# Obsidian vault (long-term memory)\nThe user's Obsidian vault at {vault} is your long-term memory. "
           "Use obsidian_search / obsidian_read to recall, obsidian_write to save durable facts as markdown notes "
           "with [[wikilinks]] and #tags, and obsidian_links to follow backlinks. Never write outside the vault."]
    try:
        notes = obsidian.relevant_notes(vault, query) if query else []
    except Exception:  # retrieval must never break a turn
        notes = []
    if notes:
        out.append("# Relevant vault notes (keyword match for this message)\n"
                   + "\n\n".join(f"## {n['path']}\n{n['content']}" for n in notes))
    return out


def _preview(args: dict) -> str:
    for key in ("command", "path", "url", "name", "action"):
        if args.get(key):
            return str(args[key])[:200]
    return json.dumps(args, ensure_ascii=False)[:200]


class Agent:
    def __init__(self, rec: dict, store: SessionStore, ctx: ToolContext, emit: EmitFn):
        self.rec = rec
        self.store = store
        self.ctx = ctx
        self.emit = emit
        self.interrupted = False

    def interrupt(self) -> None:
        self.interrupted = True

    async def run_turn(self, user_text: str, attachments: list[dict] | None = None) -> str:
        from neovarch import uploads
        cfg = cfgmod.load_config()
        from neovarch import models as modelsmod
        override = self.rec.get("model_override") or {}
        if override.get("model") or override.get("provider"):
            # The chat's own pick (composer session pick / Perusahaan agent model) wins.
            endpoint = session_settings.effective_endpoint(cfg, self.rec)
        else:
            endpoint = modelsmod.endpoint_for(cfg, "session:" + str(self.rec.get("id") or ""))
        self._effort = session_settings.wire_effort(session_settings.effective_effort(cfg, self.rec))
        self._skipped_notice = False
        vision = uploads.supports_vision(cfg, endpoint)
        self.ctx.approvals_mode = str(cfgmod.get_path(cfg, "approvals.mode", "ask") or "ask")
        max_turns = int(cfgmod.get_path(cfg, "agent.max_turns", 30) or 30)
        self.interrupted = False
        turn_started = time.time()
        self.ctx.outbox = []
        if not self.ctx.session_id:
            self.ctx.session_id = str(self.rec.get("id") or "")
        messages = self.rec["messages"]
        first_new = len(messages)
        user_msg: dict[str, Any] = {"role": "user", "content": user_text, "ts": time.time()}
        if attachments:
            user_msg["attachments"] = [dict(a) for a in attachments]
            if not vision and any(a.get("kind") == "image" for a in attachments):
                self.emit("attachment.notice", {"level": "warning", "message": uploads.VISION_NOTICE})
        messages.append(user_msg)
        if not self.rec.get("title"):
            first = user_text.strip().splitlines()[0][:60] if user_text.strip() else ""
            if not first and attachments:
                first = ("Lampiran: " + ", ".join(a.get("name", "") for a in attachments))[:60]
            self.rec["title"] = first
            if self.rec["title"]:
                self.emit("session.title", {"title": self.rec["title"]})
        self.rec["model"] = endpoint["model"]
        self.store.save(self.rec)

        self.emit("message.start", {})
        started = time.monotonic()
        final_text = ""
        usage: dict[str, Any] = {}
        error = None
        persona = ""
        company_persona = getattr(self.ctx, "persona", None)
        if company_persona is not None:  # a Perusahaan agent: name, title, ticket, goal ancestry
            try:
                persona = company_persona()
            except Exception:  # a persona glitch must never break a turn
                persona = ""
        if not persona:
            try:
                persona = persona_prompt(self.rec.get("id"), self.ctx.office() if self.ctx.office else None)
            except Exception:  # the Kantor must never break a turn
                persona = persona_prompt(self.rec.get("id"), None)
        if "@kantor" in user_text.lower() and self.ctx.office is not None:
            try:  # `@kantor` attaches the live Kantor state to this turn
                from neovarch.tools import office_summary
                persona += "\n\n# Kantor saat ini (diminta lewat @kantor)\n" + office_summary(self.ctx.office())
            except Exception:
                pass
        sys_prompt = system_prompt(cfg, self.ctx.cwd, user_text, persona)
        pinned = bool(override.get("model") or override.get("provider")) or \
            modelsmod.agent_model(cfg, "session:" + str(self.rec.get("id") or "x"))["source"] == "agent"
        # The endpoint this turn really uses: a free 9Router model that is cooling down
        # after a rate limit is skipped up front, unless the agent pinned it.
        active = dict(endpoint)
        self.tried: list[str] = []
        self.fallbacks: list[dict] = []
        from neovarch import router9
        if (endpoint.get("provider") == router9.PROVIDER and not pinned
                and router9.is_free_model(endpoint["model"]) and router9.cooldown_left(endpoint["model"])):
            alt = next((m for m in router9.fallback_candidates(endpoint["model"])
                        if not router9.cooldown_left(m)), None)
            if alt:
                self._announce_fallback(endpoint["model"], alt, "cooldown", None)
                active["model"] = alt
        try:
            for _ in range(max_turns):
                if self.interrupted:
                    error = "interrupted"
                    break
                wire = [{"role": "system", "content": sys_prompt}] + wire_messages(messages, vision, self.ctx.cwd)
                comp: Completion = await self._complete(active, wire, pinned)
                usage = comp.usage or usage
                assistant: dict[str, Any] = {"role": "assistant", "content": comp.text, "ts": time.time()}
                if comp.reasoning:
                    assistant["reasoning"] = comp.reasoning
                if comp.tool_calls:
                    assistant["tool_calls"] = [{"id": c.id, "type": "function",
                                                "function": {"name": c.name, "arguments": c.arguments or "{}"}}
                                               for c in comp.tool_calls]
                messages.append(assistant)
                self.store.save(self.rec)
                if not comp.tool_calls:
                    final_text = comp.text
                    break
                for call in comp.tool_calls:
                    sent_before = len(self.ctx.outbox)
                    args = call.parsed_args()
                    self.emit("tool.start", {"tool_id": call.id, "name": call.name, "args": args,
                                             "args_text": call.arguments, "preview": _preview(args)})
                    t0 = time.monotonic()
                    result = await run_tool(call.name, args, self.ctx) if not self.interrupted else "interrupted"
                    dur = time.monotonic() - t0
                    _log.info("tool %s session=%s %.2fs", call.name, self.rec.get("id"), dur)
                    messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                                     "content": result, "ts": time.time()})
                    self.store.save(self.rec)
                    self.emit("tool.complete", {"tool_id": call.id, "name": call.name,
                                                "summary": result.splitlines()[0][:160] if result else "",
                                                "result": result[:4000], "result_text": result[:4000],
                                                "duration_s": round(dur, 2)})
                    for meta in self.ctx.outbox[sent_before:]:
                        self._emit_attachment(meta)
            else:
                error = f"stopped after {max_turns} model calls"
        except LLMError as exc:
            error = _explain(str(exc), active, self.tried)
        if error and error != "interrupted":
            _log.warning("turn error session=%s model=%s: %s", self.rec.get("id"), endpoint.get("model"), error)
            self.emit("error", {"message": error})
        sent = self._finish_attachments(messages, first_new, final_text, user_text, turn_started)
        elapsed = max(time.monotonic() - started, 1e-6)
        out_tokens = int(usage.get("completion_tokens") or 0)
        ctx_len = int(cfgmod.get_path(cfg, "model.context_length", 128000) or 128000)
        self.emit("message.complete", {
            "text": final_text,
            "usage": {**usage, "avg_tps": round(out_tokens / elapsed, 1) if out_tokens else None,
                      "context_percent": round(100 * int(usage.get("prompt_tokens") or 0) / ctx_len, 1)},
            **({"error": error} if error else {}),
            **({"model": active["model"], "model_fallback": self.fallbacks} if self.fallbacks else {}),
            **({"status": "interrupted"} if error == "interrupted" else {}),
            **({"attachments": sent} if sent else {}),
        })
        return final_text

    # ---- files the agent sends into the chat (send_file / final-answer paths) ----
    def _emit_attachment(self, meta: dict) -> None:
        from neovarch import uploads
        self.emit("message.attachment", {"attachment": uploads.public(meta)})

    def _finish_attachments(self, messages: list[dict], first_new: int, final_text: str,
                            user_text: str, turn_started: float) -> list[dict]:
        """Store this turn's outgoing files on its last assistant message.

        Safety net: when the person asked for a file to be sent and the model only
        named fresh files by path in its answer, those files are attached as well."""
        from neovarch import outbox, uploads
        staged = list(self.ctx.outbox)
        if final_text and outbox.wants_file(user_text):
            have = {m.get("source_path") for m in staged}
            store = self.ctx.uploads or uploads.UploadStore()
            for p in outbox.paths_in_text(final_text, self.ctx.cwd, turn_started):
                if str(p) in have or len(staged) >= outbox.MAX_FILES_PER_TURN:
                    continue
                try:
                    meta = outbox.stage(store, self.ctx.session_id, str(p), self.ctx.cwd)
                except (outbox.SendError, OSError) as exc:
                    _log.warning("auto attach %s failed: %s", p, exc)
                    continue
                meta["auto"] = True
                staged.append(meta)
                have.add(str(p))
                self._emit_attachment(meta)
        if not staged:
            return []
        host = next((m for m in reversed(messages[first_new:]) if m.get("role") == "assistant"), None)
        if host is None:
            host = {"role": "assistant", "content": "", "ts": time.time()}
            messages.append(host)
        host["attachments"] = [*(host.get("attachments") or []), *staged]
        self.store.save(self.rec)
        self.ctx.outbox = []
        return [uploads.public(m) for m in staged]


    async def _stream(self, endpoint: dict, wire: list[dict], started: list[bool],
                      on_first: Callable[[], None] | None = None) -> Completion:
        def first() -> None:
            if not started[0]:
                started[0] = True
                if on_first:
                    on_first()  # e.g. the fallback notice, so it lands before the answer

        def on_text(t: str) -> None:
            first()
            self.emit("message.delta", {"text": t})

        def on_reasoning(t: str) -> None:
            first()
            self.emit("reasoning.delta", {"text": t})

        return await stream_chat(
            base_url=endpoint["base_url"], api_key=endpoint["api_key"], model=endpoint["model"],
            messages=wire, tools=tool_schemas(self.ctx), on_text=on_text, on_reasoning=on_reasoning,
            extra_headers=endpoint.get("headers") or None,
            verify_ssl=endpoint.get("verify_ssl", True),
            reasoning_effort=getattr(self, "_effort", None),
        )

    async def _complete(self, active: dict, wire: list[dict], pinned: bool) -> Completion:
        """One model call. When a free 9Router model answers 429 / 5xx before streaming
        anything, the same request is retried once per next free model; ``active`` then
        keeps the model that answered for the rest of the turn. The saved default and
        per-agent models are never changed."""
        from neovarch import router9
        started = [False]
        try:
            comp = await self._stream(active, wire, started)
            router9.clear_limited(active["model"])
            self._note_reasoning_skipped(comp)
            return comp
        except LLMError as exc:
            first = exc
            status = router9.retryable_status(str(exc))
            if (started[0] or status is None or active.get("provider") != router9.PROVIDER
                    or not router9.is_free_model(active["model"])):
                raise
        limited = active["model"]
        router9.mark_limited(limited)
        self.tried.append(limited)
        last: LLMError = first
        for cand in router9.fallback_candidates(limited):
            if self.interrupted or cand in self.tried:
                continue
            attempt = {**active, "model": cand}
            started = [False]
            announced = [False]

            def announce(cand: str = cand) -> None:
                announced[0] = True
                self._announce_fallback(limited, cand, "rate_limited" if status == 429 else "unavailable", status)
            try:
                comp = await self._stream(attempt, wire, started, announce)
            except LLMError as exc:
                last = exc
                code = router9.retryable_status(str(exc))
                if started[0] or code is None:
                    raise
                router9.mark_limited(cand)
                self.tried.append(cand)
                continue
            router9.clear_limited(cand)
            self._note_reasoning_skipped(comp)
            if not announced[0]:  # tool calls only, no text streamed
                announce()
            active["model"] = cand
            return comp
        raise last

    def _note_reasoning_skipped(self, comp: Completion) -> None:
        if getattr(comp, "reasoning_skipped", False):
            self._effort = None  # the model rejected it; do not resend this turn
            if not getattr(self, "_skipped_notice", False):
                self._skipped_notice = True
                self.emit("status", {"kind": "notice", "text": "Model ini tidak mendukung tingkat penalaran; "
                                                                "dikirim tanpa pengaturan itu."})

    def _announce_fallback(self, limited: str, used: str, reason: str, status: int | None) -> None:
        from neovarch import router9
        text = router9.fallback_notice(limited, used)
        info = {"from": limited, "to": used, "reason": reason, "status": status,
                "cooldown_s": round(router9.cooldown_left(limited)), "text": text}
        self.fallbacks.append(info)
        self.emit("model.fallback", info)
        # Desktop paints status.update kind=fallback as a line in the transcript.
        self.emit("status.update", {"kind": "fallback", "text": "\u26a0\ufe0f " + text})


def _explain(error: str, endpoint: dict, tried: list[str] | None = None) -> str:
    """A 9Router failure the user can act on, in Indonesian."""
    if endpoint.get("provider") != "9router":
        return error
    from neovarch import router9
    root = router9.root_url(endpoint.get("base_url") or router9.DEFAULT_BASE_URL)
    if error.startswith("could not reach"):
        return (f"9Router belum berjalan di {root}. Buka Pengaturan \u25b8 Model lalu tekan Jalankan, "
                f"atau pasang dulu: {router9.INSTALL_COMMAND}")
    if "HTTP 401" in error:
        return (f"9Router meminta API key. Buka dashboard 9Router ({root}/dashboard) \u25b8 Endpoint, "
                "buat API key, lalu tempel di Pengaturan \u25b8 Model.")
    if tried and len(tried) > 1:
        return ("Semua model gratis yang dicoba sedang dibatasi atau tidak tersedia ("
                + ", ".join(tried) + "). Coba lagi beberapa menit lagi, atau pilih model lain "
                "dari pemilih model di kolom chat.")
    if "HTTP 429" in error:
        model = endpoint.get("model") or "model ini"
        if "FreeUsageLimit" in error or str(model).startswith("oc/"):
            return (f"Batas pemakaian gratis OpenCode Free untuk {model} sedang habis. Coba lagi sebentar "
                    "lagi, atau pilih model lain dari pemilih model di kolom chat.")
        return (f"9Router sedang membatasi permintaan ke {model} (HTTP 429). Coba lagi sebentar lagi, "
                "atau pilih model lain dari pemilih model di kolom chat.")
    return error


def wire_messages(messages: list[dict], vision: bool, cwd: Path) -> list[dict]:
    """Stored transcript -> provider wire. User turns with attachments become content
    parts (images as data URLs for the last few turns when the model sees images);
    ``@file:`` refs of the newest user turn get the file text appended."""
    from neovarch import uploads
    image_turns = [i for i, m in enumerate(messages) if m.get("role") == "user"
                   and any(isinstance(a, dict) and a.get("kind") == "image" for a in m.get("attachments") or [])]
    recent = set(image_turns[-uploads.IMAGE_HISTORY:])
    last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    out = []
    for i, m in enumerate(messages):
        if m.get("role") == "user" and m.get("attachments"):
            w = uploads.user_wire(m, vision, i in recent)
        else:
            w = _wire(m)
        if i == last_user and "@file:" in str(m.get("content") or ""):
            if isinstance(w["content"], str):
                w["content"] = uploads.expand_file_refs(w["content"], cwd)
            elif isinstance(w["content"], list) and w["content"] and w["content"][0].get("type") == "text":
                w["content"][0]["text"] = uploads.expand_file_refs(w["content"][0]["text"], cwd)
        out.append(w)
    return out


def _wire(m: dict) -> dict:
    out = {"role": m["role"], "content": m.get("content") or ("" if m["role"] != "assistant" else None)}
    if m["role"] == "assistant" and m.get("tool_calls"):
        out["tool_calls"] = m["tool_calls"]
        if not out["content"]:
            out["content"] = None
    if m["role"] == "tool":
        out["tool_call_id"] = m.get("tool_call_id", "")
    return out


def now_text(cfg: dict) -> str:
    """Local date/time for the prompt, in Settings › Perilaku › timezone when set (e.g. Asia/Jakarta)."""
    tz = str(cfgmod.get_path(cfg, "timezone", "") or "").strip()
    if tz:
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M ") + tz
        except Exception:
            pass  # unknown zone name: fall back to the PC's clock
    return time.strftime("%Y-%m-%d %H:%M %Z")


def default_cwd() -> Path:
    """Where new chats start: NEOVARCH_CWD, else Settings › Ruang kerja › Proyek (terminal.cwd), else here."""
    env = os.environ.get("NEOVARCH_CWD")
    if env:
        return Path(env)
    try:
        raw = str(cfgmod.get_path(cfgmod.load_config(), "terminal.cwd", "") or "").strip()
    except Exception:
        raw = ""
    if raw:
        p = Path(os.path.expanduser(raw))
        if p.is_dir():
            return p
    return Path(os.getcwd())
