"""Self-diagnosis behind ``/perbaiki`` and ``/fix``: gather, redact, explain, propose.

Works without a model on purpose: when the model itself is the problem (wrong
key, router down) the report still arrives. It reads

* the core's own logs (``agent.log``, ``errors.log``),
* the desktop (Electron) logs when they exist on this PC,
* failed tool calls in the most recent chats,
* the configuration (secrets removed),

then turns known patterns into findings with an Indonesian explanation and a
proposed fix. ``kind`` of a fix says how it is applied: ``config`` and ``skill``
fixes are applied automatically (undoable), ``code`` fixes go through
:mod:`neovarch.selfpatch` and the user's approval, ``manual`` ones are steps the
user takes.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from neovarch import config as cfgmod
from neovarch.paths import neovarch_home

TAIL_LINES = 120
SECRET_KEY_RX = re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|bearer|cookie|"
                           r"client[_-]?secret|private[_-]?key|access[_-]?key|session)")
_PATTERNS = [
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-+/=]{8,}"), r"\1 [DISAMARKAN]"),
    (re.compile(r"\b(sk|pk|rk|gsk|xai|ghp|gho|ghu|ghs|github_pat|glpat|hf|nvapi|sk-or-v1|sk-ant)[-_][A-Za-z0-9_\-]{8,}"),
     "[DISAMARKAN]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"), "[DISAMARKAN]"),
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"), "[DISAMARKAN]"),  # Telegram bot tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"), "[DISAMARKAN]"),  # JWT
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password|passwd|client_secret|access_key)[\"']?\s*[:=]\s*[\"']?)"
                r"[^\s\"',}]{4,}"), r"\1[DISAMARKAN]"),
    (re.compile(r"(?i)([?&](?:token|key|api_key|access_token|sig)=)[^&\s]+"), r"\1[DISAMARKAN]"),
    (re.compile(r"(?i)(https?://[^:/\s]+:)[^@\s]+@"), r"\1[DISAMARKAN]@"),
]


def redact(text: str) -> str:
    """Remove anything that looks like a credential. Also strips values found in the user's .env."""
    out = str(text or "")
    for rx, rep in _PATTERNS:
        out = rx.sub(rep, out)
    try:
        for v in cfgmod.read_env_file().values():
            if v and len(v) >= 6:
                out = out.replace(v, "[DISAMARKAN]")
    except Exception:
        pass
    return out


def redact_config(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: redact_config(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_config(v, key) for v in value]
    if isinstance(value, str) and SECRET_KEY_RX.search(key) and not key.endswith("_env") and value:
        return "[DISAMARKAN]"
    if isinstance(value, str):
        return redact(value)
    return value


def _tail(path: Path, n: int = TAIL_LINES) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [redact(ln) for ln in lines[-n:]]


def desktop_log_dirs() -> list[Path]:
    home = Path.home()
    cands = [os.environ.get("NEOVARCH_DESKTOP_LOG_DIR") or ""]
    for app in ("Neovarch", "neovarch", "Neovarch Agent", "neovarch-desktop", "Neovarch Desktop"):
        cands += [str(home / ".config" / app / "logs"), str(home / ".config" / app)]
        if os.environ.get("APPDATA"):
            cands += [str(Path(os.environ["APPDATA"]) / app / "logs"), str(Path(os.environ["APPDATA"]) / app)]
    cands.append(str(neovarch_home() / "logs" / "desktop"))
    seen, out = set(), []
    for c in cands:
        if c and c not in seen and Path(c).is_dir():
            seen.add(c)
            out.append(Path(c))
    return out


def collect(store=None, sessions: int = 8) -> dict[str, Any]:
    """Everything the report needs, already redacted."""
    from neovarch.logs import FILES, log_dir
    logs = {name: _tail(log_dir() / fname) for name, fname in FILES.items() if (log_dir() / fname).exists()}
    desktop: dict[str, list[str]] = {}
    for d in desktop_log_dirs():
        for f in sorted(d.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
            desktop[str(f)] = _tail(f, 80)
    failures = failed_tool_calls(store, sessions) if store is not None else []
    cfg = cfgmod.load_config()
    ep = cfgmod.resolve_endpoint(cfg)
    return {"logs": logs, "desktop_logs": desktop, "failed_tools": failures,
            "config": redact_config(cfg),
            "endpoint": {"provider": ep["provider"], "model": ep["model"], "base_url": redact(ep["base_url"]),
                         "has_key": bool(ep["api_key"])},
            "runtime": {"python": sys.version.split()[0], "platform": sys.platform,
                        "frozen": bool(getattr(sys, "frozen", False)), "home": str(neovarch_home())},
            "collected_at": time.time()}


def failed_tool_calls(store, sessions: int = 8, limit: int = 20) -> list[dict]:
    out: list[dict] = []
    try:
        rows = store.list(limit=sessions)
    except Exception:
        return out
    for row in rows:
        try:
            rec = store.load(row["id"])
        except Exception:
            rec = None
        if not rec:
            continue
        calls: dict[str, dict] = {}
        for m in rec.get("messages", []):
            for tc in m.get("tool_calls") or []:
                calls[tc.get("id", "")] = tc
            if m.get("role") == "tool":
                content = str(m.get("content") or "")
                if content.lstrip().lower().startswith(("error:", "refused:", "denied:")) or \
                        re.match(r"exit code [1-9]", content):
                    tc = calls.get(m.get("tool_call_id") or "", {})
                    args = str((tc.get("function") or {}).get("arguments") or "")[:200]
                    out.append({"session": rec["id"], "title": rec.get("title") or "", "tool": m.get("name"),
                                "args": redact(args), "error": redact(content.splitlines()[0][:300] if content else ""),
                                "ts": m.get("ts")})
    out.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    return out[:limit]


# --------------------------------------------------------------- analysis --

def analyze(data: dict) -> list[dict]:
    """Known problems → findings {id, title, explain, fix{kind, ...}}."""
    findings: list[dict] = []
    text = "\n".join(sum(data.get("logs", {}).values(), []) + sum(data.get("desktop_logs", {}).values(), []))
    ep = data.get("endpoint") or {}
    cfg = data.get("config") or {}

    def add(fid: str, title: str, explain: str, fix: dict) -> None:
        if not any(f["id"] == fid for f in findings):
            findings.append({"id": fid, "title": title, "explain": explain, "fix": fix})

    if not ep.get("model"):
        add("no-model", "Belum ada model bawaan",
            "Agen tidak tahu model mana yang dipakai, jadi setiap obrolan gagal sebelum mulai.",
            {"kind": "manual", "steps": "Buka Pengaturan ▸ Model lalu pilih model, atau minta aku: "
                                        "\"ganti model bawaan ke <nama model>\"."})
    if ep.get("provider") == "9router" and re.search(r"could not reach|ECONNREFUSED|9Router belum berjalan", text):
        add("router-down", "9Router tidak berjalan",
            "Penyedia model bawaan (9Router lokal) tidak bisa dihubungi, jadi model tidak menjawab.",
            {"kind": "config", "key": "router9.autostart", "value": True,
             "steps": "Nyalakan autostart 9Router, lalu tekan Jalankan di Pengaturan ▸ Model."})
    if re.search(r"HTTP 401|invalid api key|Incorrect API key|unauthorized", text, re.I):
        add("auth", "Kunci API ditolak (HTTP 401)",
            "Penyedia model menolak kunci API yang tersimpan. Kunci tidak pernah kutampilkan; "
            "tempel kunci baru lewat Pengaturan ▸ Model.",
            {"kind": "manual", "steps": "Pengaturan ▸ Model ▸ tempel API key baru untuk penyedia ini."})
    if re.search(r"HTTP 429|rate.?limit|FreeUsageLimit", text, re.I):
        add("rate-limit", "Model dibatasi (HTTP 429)",
            "Model gratis sedang kena batas pemakaian. Agen otomatis mencoba model gratis lain, "
            "tapi kalau semuanya penuh obrolan tetap gagal.",
            {"kind": "manual", "steps": "Tunggu beberapa menit atau pilih model lain dari pemilih model."})
    if re.search(r"context length|maximum context|too many tokens|context_length_exceeded", text, re.I):
        add("context", "Konteks model penuh",
            "Percakapan terlalu panjang untuk jendela konteks model ini.",
            {"kind": "config", "key": "model.context_length", "value": 32000,
             "steps": "Turunkan panjang konteks agar riwayat dipadatkan lebih awal, atau mulai obrolan baru."})
    if re.search(r"does not support|reasoning_effort|unsupported parameter", text, re.I):
        add("reasoning", "Model tidak mendukung tingkat penalaran",
            "Model menolak parameter penalaran; agen sudah mengirim ulang tanpa parameter itu.",
            {"kind": "config", "key": "agent.reasoning_effort", "value": "",
             "steps": "Kosongkan tingkat penalaran bawaan."})
    vault = (cfg.get("memory") or {}).get("obsidian_vault") or ""
    if vault and not Path(os.path.expanduser(str(vault))).is_dir():
        add("vault-missing", "Folder vault Obsidian tidak ada",
            f"Vault yang diatur ({vault}) tidak ditemukan, jadi memori jangka panjang tidak terbaca.",
            {"kind": "config", "key": "memory.obsidian_enabled", "value": False,
             "steps": "Matikan sementara vault, lalu pilih folder yang benar di Pengaturan ▸ Memori & Skill."})
    by_tool: dict[str, list[dict]] = {}
    for f in data.get("failed_tools") or []:
        by_tool.setdefault(str(f.get("tool")), []).append(f)
    for tool, rows in by_tool.items():
        if len(rows) >= 2:
            sample = rows[0]["error"]
            add(f"tool-{tool}", f"Alat `{tool}` gagal {len(rows)} kali",
                f"Contoh error terbaru: {sample}",
                {"kind": "skill", "skill": "catatan-perbaikan",
                 "note": f"Alat {tool} sering gagal dengan: {sample}. Periksa argumen/izin sebelum memanggilnya.",
                 "steps": "Simpan catatan di skill agar agen menghindari kesalahan yang sama."})
    tracebacks = re.findall(r'File "([^"]+neovarch[^"]+)", line (\d+)', text)
    if tracebacks:
        path, line = tracebacks[-1]
        add("traceback", "Error di kode core",
            f"Log mencatat traceback dari kode aplikasi ({Path(path).name}:{line}). Ini perlu perbaikan kode.",
            {"kind": "code", "file": path, "line": int(line),
             "steps": "Aku bisa menyiapkan patch di branch lokal baru, menjalankan tes, lalu menerapkannya setelah "
                      "kamu tekan Setujui (hanya untuk instalasi dari kode sumber/git)."})
    return findings


def render(data: dict, findings: list[dict], applied: list[str] | None = None) -> str:
    applied = applied or []
    lines = ["**Diagnosis Neovarch**", ""]
    ep = data.get("endpoint") or {}
    lines.append(f"Model: `{ep.get('model') or '-'}` via `{ep.get('provider') or '-'}` "
                 f"(kunci API: {'ada' if ep.get('has_key') else 'tidak ada'})")
    if not findings:
        lines += ["", "Tidak ada masalah yang dikenali di log dan pengaturan. Kalau ada yang terasa salah, "
                      "ceritakan gejalanya: `/perbaiki <apa yang terjadi>`."]
    for i, f in enumerate(findings, 1):
        lines += ["", f"**{i}. {f['title']}**", f["explain"]]
        fix = f["fix"]
        if f["id"] in applied:
            lines.append(f"✅ Sudah diperbaiki otomatis: {fix.get('steps')} (pulihkan dengan `/undo`).")
        elif fix.get("kind") == "code":
            lines.append(f"🛠 Usulan: {fix.get('steps')}")
        else:
            lines.append(f"👉 Usulan: {fix.get('steps')}")
    errs = data.get("logs", {}).get("errors") or []
    ftools = data.get("failed_tools") or []
    lines += ["", "**Bukti**"]
    if errs:
        lines.append("errors.log (terakhir):")
        lines.append("```\n" + "\n".join(errs[-5:]) + "\n```")
    if ftools:
        lines.append("Alat yang gagal baru-baru ini:")
        for f in ftools[:5]:
            lines.append(f"- `{f['tool']}`: {f['error']}")
    if not errs and not ftools:
        lines.append("- errors.log kosong dan tidak ada panggilan alat yang gagal di obrolan terakhir.")
    lines += ["", "**Batasan**", "- Rahasia (API key, token) disamarkan dan tidak pernah ditampilkan.",
              "- Log desktop dibaca hanya kalau ada di PC ini (" + (", ".join(data.get("desktop_logs", {})) or
                                                                   "tidak ditemukan") + ")."]
    return "\n".join(lines)


def apply_safe_fixes(findings: list[dict], session_id: str = "") -> list[str]:
    """Apply config/skill fixes (undoable); returns the ids that were applied."""
    from neovarch import selfedit
    done: list[str] = []
    for f in findings:
        fix = f["fix"]
        try:
            if fix.get("kind") == "config":
                key = fix["key"]
                if key in selfedit.SETTINGS:
                    selfedit.settings_update(key, fix["value"], session_id=session_id)
                else:  # router9.autostart and friends: same journal, outside the agent's general whitelist
                    cfg = cfgmod.load_config()
                    before = cfgmod.get_path(cfg, key)
                    selfedit.record("config", "set", key, None, summary=f"perbaikan otomatis {f['id']}",
                                    before=before, after=fix["value"], session_id=session_id,
                                    extra={"raw_before": before})
                    cfgmod.set_path(cfg, key, fix["value"])
                    cfgmod.save_config(cfg)
                done.append(f["id"])
            elif fix.get("kind") == "skill":
                name = fix.get("skill") or "catatan-perbaikan"
                try:
                    selfedit.skill_manage("view", name)
                    exists = True
                except selfedit.SelfEditError:
                    exists = False
                if exists:
                    cur = selfedit.skill_manage("view", name)["content"]
                    if fix["note"] in cur:
                        continue
                    selfedit.skill_manage("edit", name, content=cur.rstrip() + f"\n- {fix['note']}\n",
                                          session_id=session_id)
                else:
                    selfedit.skill_manage("create", name, description="Pelajaran dari perbaikan diri: kesalahan yang "
                                          "pernah terjadi dan cara menghindarinya.",
                                          content=f"# Catatan perbaikan\n\n- {fix['note']}\n", session_id=session_id)
                done.append(f["id"])
        except Exception:  # one bad fix must not stop the report
            continue
    return done


def run(store=None, session_id: str = "", apply: bool = True) -> dict:
    data = collect(store)
    findings = analyze(data)
    applied = apply_safe_fixes(findings, session_id) if apply else []
    return {"findings": findings, "applied": applied, "report": render(data, findings, applied), "data": data}
