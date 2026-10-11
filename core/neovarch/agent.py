"""The agent loop: stream a completion, run the tools it asks for, repeat."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from neovarch import config as cfgmod
from neovarch import session_settings
from neovarch import tempest
from neovarch import tempest_ckpt
from neovarch import tempest_lint
from neovarch import tempest_progress
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


def system_sections(cfg: dict, cwd: Path, query: str = "", persona: str = "",
                    stable: bool = False) -> list[tuple[str, str]]:
    """The system prompt as ordered (key, text) sections; see :func:`system_prompt`.

    Keys: soul, app, persona, extra, memory, vault, skills, platform, cwd. Tempest cache v2 freezes
    these per session and appends a note for the ones that change later."""
    parts: list[tuple[str, str]] = [("soul", cfgmod.soul_text().strip()), ("app", APP_KNOWLEDGE)]
    if persona:
        parts.append(("persona", persona))
    extra = str(cfgmod.get_path(cfg, "agent.system_prompt", "") or "").strip()
    if extra:
        parts.append(("extra", extra))
    home = cfgmod.neovarch_home()
    notes = sorted((home / "memory").glob("*.md")) if (home / "memory").exists() else []
    if notes:
        mem = []
        for p in notes[:20]:
            text = p.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                mem.append(f"## {p.stem}\n{text[:4000]}")
        if mem:
            parts.append(("memory", "# Memory notes (from earlier sessions)\n" + "\n\n".join(mem)))
    vault = _vault_prompt(cfg, "" if stable else query)
    if vault:
        parts.append(("vault", "\n\n".join(vault)))
    skills = list_skills()
    if skills:
        parts.append(("skills", "# Skills (read one with the `skill` tool before using it)\n"
                      + "\n".join(f"- {s['name']}: {s['description']}" for s in skills)))
    parts.append(("platform", platform_prompt()))
    if stable:
        parts.append(("cwd", f"Current working directory: {cwd}\n(The current date/time and notes matched to a "
                             "message are given at the end of that user message under '# Konteks saat ini'.)"))
    else:
        parts.append(("cwd", f"Current working directory: {cwd}\nDate: {now_text(cfg)}"))
    return parts


STATIC_SECTIONS = ("soul", "app", "persona", "extra")


def join_sections(sections) -> str:
    return "\n\n".join(text for _, text in sections)


def system_prompt(cfg: dict, cwd: Path, query: str = "", persona: str = "", stable: bool = False) -> str:
    """The system prompt. ``stable`` (Tempest) leaves out what changes per message or minute
    (vault notes matched to this message, the clock); those go to :func:`prompt_tail`."""
    return join_sections(system_sections(cfg, cwd, query, persona, stable))


def prompt_tail(cfg: dict, query: str) -> str:
    """Tempest: the dynamic context for one user message (clock + vault notes matched to it)."""
    out = [f"# Konteks saat ini\nDate: {now_text(cfg)}"]
    try:
        from neovarch import obsidian
        vault = obsidian.vault_path(cfg)
        notes = obsidian.relevant_notes(vault, query) if (query and vault is not None and vault.is_dir()) else []
    except Exception:  # retrieval must never break a turn
        notes = []
    if notes:
        out.append("# Relevant vault notes (keyword match for this message)\n"
                   + "\n\n".join(f"## {n['path']}\n{n['content']}" for n in notes))
    return "\n\n".join(out)


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
        st = tempest.for_model(tempest.settings(cfg), endpoint.get("model") or "")  # None = legacy, unchanged
        self._tempest = st
        self._changed: list[str] = []
        self._before: dict[str, bytes | None] = {}  # content of each changed file before this turn
        verify_attempts = 0
        lint_attempts = 0
        self._ckpt = None       # ShadowRepo once the first modifying tool of this turn runs
        self._ckpt_base = None  # checkpoint sha taken before that tool
        verify_cmd = tempest.detect_verify(self.ctx.cwd) if st else None
        obs_dir = cfgmod.neovarch_home() / "obs" / str(self.rec.get("id") or "session")
        messages = self.rec["messages"]
        first_new = len(messages)
        user_msg: dict[str, Any] = {"role": "user", "content": user_text, "ts": time.time()}
        self._progress = None
        if st:
            user_msg["wire_tail"] = prompt_tail(cfg, user_text)
            if st.get("progress"):
                self._progress = tempest_progress.Progress(self.ctx.cwd, cfgmod.neovarch_home())
                if not any(m.get("role") == "assistant" for m in messages):
                    note = tempest_progress.session_start_note(self._progress)
                    if note:  # a fresh chat continues an unfinished plan instead of redoing it
                        user_msg["wire_tail"] += "\n\n" + note
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
        kantor = ""
        if "@kantor" in user_text.lower() and self.ctx.office is not None:
            try:  # `@kantor` attaches the live Kantor state to this turn
                from neovarch.tools import office_summary
                kantor = "# Kantor saat ini (diminta lewat @kantor)\n" + office_summary(self.ctx.office())
            except Exception:
                pass
        system_split = None
        if st and st.get("cache_v2"):
            # Cache layout v2: the system prompt is frozen for the session; a later change
            # rides on this user message as an appended note (the prefix never changes).
            sections = [[k, v] for k, v in system_sections(cfg, self.ctx.cwd, user_text, persona, stable=True)]
            prefix = self.rec.get("tempest_prefix")
            tail_extra = []
            if not prefix or not prefix.get("frozen"):
                prefix = {"frozen": sections, "current": sections}
                self.rec["tempest_prefix"] = prefix
            else:
                note = tempest.config_change_note(prefix.get("current") or prefix["frozen"], sections)
                if note:
                    tail_extra.append(note)
                    prefix["current"] = sections
            if kantor:
                tail_extra.append(kantor)
            if tail_extra:
                user_msg["wire_tail"] = (user_msg.get("wire_tail") or "") + "\n\n" + "\n\n".join(tail_extra)
            frozen = prefix["frozen"]
            sys_prompt = join_sections(frozen)
            static = [x for x in frozen if x[0] in STATIC_SECTIONS]
            if static and len(static) < len(frozen) and frozen[:len(static)] == static:
                system_split = len(join_sections(static)) + 2
            self.store.save(self.rec)
        else:
            if kantor:
                persona += "\n\n" + kantor
            sys_prompt = system_prompt(cfg, self.ctx.cwd, user_text, persona, stable=bool(st))
        window = int(cfgmod.get_path(cfg, "model.context_length", 128000) or 128000)
        breakpoints = tempest.wants_breakpoints(st, endpoint)
        lint_prefix = bool(st and st.get("cache_v2") and not st.get("mask"))
        self._turn_prompt = 0
        self._turn_cached = 0
        prefix_breaks = 0
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
                if st and st.get("compact"):
                    wire, sys_prompt, system_split = self._compact(wire, messages, st, window, obs_dir,
                                                                   sys_prompt, system_split)
                if st:
                    wire = tempest.mask_wire(wire, st)
                if breakpoints:
                    wire = tempest.place_breakpoints(wire, system_split, getattr(self, "_prev_last", None),
                                                     str(st.get("cache_ttl") or ""))
                    self._prev_last = len(wire) - 1
                if self._progress is not None:
                    n_tool = sum(1 for m in messages if m.get("role") == "tool")
                    if n_tool >= int(st.get("recite_after") or 10):
                        plan = tempest_progress.recitation(self._progress)
                        if plan:  # ephemeral trailing note: nothing earlier changes
                            wire = wire + [{"role": "user", "content": plan}]
                if lint_prefix:
                    bad = tempest.prefix_violation(getattr(self, "_prev_wire", None), wire)
                    if bad is not None:
                        prefix_breaks += 1
                        _log.warning("tempest prefix changed at message %d session=%s", bad, self.rec.get("id"))
                    self._prev_wire = wire
                comp: Completion = await self._complete(active, wire, pinned)
                usage = comp.usage or usage
                if st:
                    self._turn_prompt += int((comp.usage or {}).get("prompt_tokens") or 0)
                    self._turn_cached += tempest.cached_tokens(comp.usage)
                assistant: dict[str, Any] = {"role": "assistant", "content": comp.text, "ts": time.time()}
                if comp.reasoning:
                    assistant["reasoning"] = comp.reasoning
                if comp.tool_calls:
                    assistant["tool_calls"] = [{"id": c.id, "type": "function",
                                                "function": {"name": c.name, "arguments": c.arguments or "{}"}}
                                               for c in comp.tool_calls]
                messages.append(assistant)
                self.store.save(self.rec)
                if st and len(messages) >= 2 and messages[-2].get("kind") == "verify" and comp.text:
                    tempest.save_reflection(cfgmod.neovarch_home() / "notes", str(self.rec.get("id") or ""),
                                          comp.text)
                if not comp.tool_calls:
                    final_text = comp.text
                    if st and st.get("lint_gate") and self._before and not self.interrupted:
                        diags = await asyncio.to_thread(self._lint_delta, st)
                        if diags and lint_attempts < int(st.get("lint_retries") or 0) \
                                and verify_attempts < st["verify_retries"]:
                            lint_attempts += 1
                            verify_attempts += 1  # one retry budget for both gates
                            self.emit("status.update", {"kind": "lint", "text": f"Diagnostik baru: {len(diags)}"})
                            messages.append({"role": "user", "kind": "lint", "ts": time.time(),
                                             "content": tempest_lint.gate_prompt(diags, lint_attempts,
                                                                                 int(st.get("lint_retries") or 0))})
                            self.store.save(self.rec)
                            continue
                        if diags:
                            final_text = comp.text + tempest_lint.leftover_note(diags)
                    if st and self._changed and verify_cmd and not self.interrupted:
                        self.emit("status.update", {"kind": "verify", "text": "Memverifikasi: " + " ".join(verify_cmd)})
                        ok, out = await asyncio.to_thread(tempest.run_verify, verify_cmd, self.ctx.cwd)
                        if ok and self._ckpt:
                            await asyncio.to_thread(self._ckpt_mark, "akhir turn: verifikasi lulus", "green")
                        if ok and self._progress is not None:
                            self._progress.mark_verified(True)
                        if not ok:
                            summary = tempest.failure_summary(out)
                            if verify_attempts < st["verify_retries"]:
                                verify_attempts += 1
                                messages.append({"role": "user", "kind": "verify", "ts": time.time(),
                                                 "content": tempest.verify_prompt(verify_cmd, summary, verify_attempts,
                                                                                st["verify_retries"])})
                                self.store.save(self.rec)
                                continue
                            final_text = final_text + tempest.escalation_note(verify_cmd, summary, st["verify_retries"])
                            error = "verification failed"
                            if self._progress is not None:
                                self._progress.mark_verified(False)
                            if self._ckpt and self._ckpt_base:
                                final_text += await asyncio.to_thread(self._rollback, verify_cmd)
                    elif st and self._ckpt and self._changed:
                        await asyncio.to_thread(self._ckpt_mark, "akhir turn", None)
                    break
                for call in comp.tool_calls:
                    sent_before = len(self.ctx.outbox)
                    args = call.parsed_args()
                    self.emit("tool.start", {"tool_id": call.id, "name": call.name, "args": args,
                                             "args_text": call.arguments, "preview": _preview(args)})
                    t0 = time.monotonic()
                    if st and st.get("checkpoints") and self._ckpt is None and not self.interrupted \
                            and call.name in ("write_file", "edit_file", "shell"):
                        await asyncio.to_thread(self._ckpt_start, st)
                    if st and call.name == "update_plan" and self._progress is not None:
                        result = self._progress.update(args, str(self.rec.get("id") or ""))
                    elif st and call.name in ("write_file", "edit_file") and not self.interrupted:
                        result = await self._checked_write(call.name, args)
                    else:
                        result = await run_tool(call.name, args, self.ctx) if not self.interrupted else "interrupted"
                    if st:
                        result = tempest.offload(result, call.name, call.id, obs_dir, st["offload_tokens"])
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
        cache_stats = {}
        if st:
            cache_stats = {"cache_read_tokens": self._turn_cached,
                           "cache_read_ratio": round(self._turn_cached / self._turn_prompt, 4) if self._turn_prompt else None,
                           "prefix_breaks": prefix_breaks}
        self.emit("message.complete", {
            "text": final_text,
            "usage": {**usage, "avg_tps": round(out_tokens / elapsed, 1) if out_tokens else None,
                      "context_percent": round(100 * int(usage.get("prompt_tokens") or 0) / ctx_len, 1),
                      **cache_stats},
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


    def _compact(self, wire: list[dict], messages: list[dict], st: dict, window: int, obs_dir: Path,
                 sys_prompt: str, system_split: int | None) -> tuple[list[dict], str, int | None]:
        """Tempest: apply the stored compaction; compact again only past ``compact_at`` x window."""
        state = self.rec.get("tempest_compact")
        out = tempest.apply_compaction(wire, state)
        tools = self._tools()
        if tempest.wire_tokens(out, tools) <= float(st.get("compact_at") or 0.5) * window:
            return out, sys_prompt, system_split
        new_state, rep = tempest.compact(messages, state, st, window, obs_dir,
                                         lambda cand: tempest.wire_tokens(tempest.apply_compaction(wire, cand), tools))
        old_masked = len((state or {}).get("masked") or {})
        if rep["masked"] == old_masked and new_state["summary_upto"] == int((state or {}).get("summary_upto") or 0):
            return out, sys_prompt, system_split  # nothing left to compact; do not break the cache for nothing
        self.rec["tempest_compact"] = new_state
        prefix = self.rec.get("tempest_prefix")
        if st.get("cache_v2") and prefix and prefix.get("current"):
            # the cache breaks here anyway: fold appended config changes into a fresh frozen prompt
            prefix["frozen"] = prefix["current"]
            sys_prompt = join_sections(prefix["frozen"])
            static = [x for x in prefix["frozen"] if x[0] in STATIC_SECTIONS]
            system_split = (len(join_sections(static)) + 2
                            if static and len(static) < len(prefix["frozen"]) and prefix["frozen"][:len(static)] == static
                            else None)
            wire = [{"role": "system", "content": sys_prompt}] + wire[1:]
        self.store.save(self.rec)
        self._prev_wire = None  # a new cache epoch: the prefix lint and breakpoints restart
        self._prev_last = None
        _log.info("tempest compaction session=%s %s", self.rec.get("id"), rep)
        self.emit("status.update", {"kind": "compact", "text": f"Konteks dipadatkan (tahap {rep['stage']}): "
                                                               f"~{rep['before']} → ~{rep['after']} token"})
        return tempest.apply_compaction(wire, new_state), sys_prompt, system_split

    def _ckpt_start(self, st: dict) -> None:
        """Tempest: snapshot the project before this turn's first modifying tool."""
        repo = tempest_ckpt.ShadowRepo(self.ctx.cwd, cfgmod.neovarch_home(), int(st.get("checkpoint_max_files") or 5000))
        ok, why = repo.usable()
        if not ok:
            _log.info("tempest checkpoints off for %s: %s", self.ctx.cwd, why)
            self._ckpt = False
            return
        try:
            self._ckpt_base = repo.checkpoint(f"awal turn ({self.rec.get('id')})")
            self._ckpt = repo
        except (tempest_ckpt.CheckpointError, OSError, subprocess.SubprocessError) as exc:
            _log.warning("tempest checkpoint failed: %s", exc)
            self._ckpt = False

    def _ckpt_mark(self, label: str, status: str | None) -> None:
        try:
            self._ckpt.checkpoint(label, status)
        except (tempest_ckpt.CheckpointError, OSError, subprocess.SubprocessError) as exc:
            _log.warning("tempest checkpoint failed: %s", exc)

    def _rollback(self, verify_cmd: list[str]) -> str:
        """Verify gave up: go back to the last green checkpoint (this turn's start, verified on
        demand when its status is unknown). The failed state stays as a checkpoint."""
        repo, base = self._ckpt, self._ckpt_base
        try:
            red = repo.checkpoint("verifikasi gagal", "red")
            status = repo.status(base)
            if status == "red":
                return ""
            repo.restore(base)
            if status != "green":
                ok, _ = tempest.run_verify(verify_cmd, self.ctx.cwd)
                if not ok:
                    repo.set_status(base, "red")
                    repo.restore(red)
                    repo.checkpoint("kembali ke versi gagal (awal turn juga merah)", "red")
                    return ""
            repo.checkpoint(f"dipulihkan ke {base[:8]}", "green")
        except (tempest_ckpt.CheckpointError, OSError, subprocess.SubprocessError) as exc:
            _log.warning("tempest rollback failed: %s", exc)
            return ""
        self.emit("status.update", {"kind": "rollback", "text": f"File dikembalikan ke checkpoint hijau {base[:8]}"})
        return (f"\n\n↩️ File dikembalikan ke checkpoint hijau terakhir ({base[:8]}, sebelum perubahan turn ini). "
                f"Versi yang gagal disimpan sebagai checkpoint {red[:8]}; pulihkan dengan `neovarch rewind {red[:8]}`.")

    def _lint_delta(self, st: dict) -> list:
        tools = None
        if str(st.get("lint_tools") or "auto") != "auto":
            tools = [t.strip() for t in str(st["lint_tools"]).split(",") if t.strip()]
        try:
            return tempest_lint.delta(self.ctx.cwd, self._before, tools, int(st.get("lint_timeout") or 60))
        except Exception as exc:  # the gate must never break a turn
            _log.warning("tempest lint gate skipped: %s", exc)
            return []

    async def _checked_write(self, name: str, args: dict) -> str:
        """Tempest: write/edit, then syntax-check .py/.json/.js/.ts; a broken file is restored."""
        try:
            from neovarch.tools import _resolve
            path = _resolve(self.ctx, str(args.get("path") or ""))
            before = path.read_bytes() if path.is_file() else None
        except Exception:
            return await run_tool(name, args, self.ctx)
        result = await run_tool(name, args, self.ctx)
        if not (result.startswith("wrote") or result.startswith("edited")):
            return result
        err = await asyncio.to_thread(tempest.syntax_error, path)
        if not err:
            self._changed.append(str(path))
            self._before.setdefault(str(path), before)
            return result
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        return (f"rejected: perubahan pada {path} membuat sintaks rusak, file dikembalikan ke isi sebelumnya.\n"
                f"{err}\nPerbaiki lalu kirim ulang {name}.")

    def _tools(self) -> list[dict]:
        tools = tool_schemas(self.ctx)
        st = getattr(self, "_tempest", None)
        if st and st.get("progress"):
            tools = tools + [tempest_progress.SCHEMA]
        if st and st.get("cache_v2"):
            tools = tempest.stable_tools(tools)
        return tools

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
            messages=wire, tools=self._tools(), on_text=on_text, on_reasoning=on_reasoning,
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
        if m.get("role") == "user" and m.get("wire_tail"):  # Tempest: dynamic context of that message
            tail = "\n\n" + str(m["wire_tail"])
            if isinstance(w["content"], str):
                w["content"] = w["content"] + tail
            elif isinstance(w["content"], list) and w["content"] and w["content"][0].get("type") == "text":
                w["content"] = [dict(w["content"][0], text=w["content"][0]["text"] + tail)] + w["content"][1:]
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
