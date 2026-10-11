"""Gateway RPCs the desktop chat uses beyond the core loop.

Kept out of server.py so feature work and the core protocol do not collide.
``handle`` returns ``NOT_HANDLED`` for anything it does not own; the gateway
then answers -32601 as before.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from neovarch import config as cfgmod
from neovarch.paths import neovarch_home

if TYPE_CHECKING:  # pragma: no cover
    from neovarch.server import Gateway

NOT_HANDLED = object()
MAX_ATTACH_BYTES = 25 * 1024 * 1024
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _uploads_dir(sid: str) -> Path:
    d = neovarch_home() / "uploads" / re.sub(r"[^A-Za-z0-9_.-]+", "_", sid or "session")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str, fallback: str) -> str:
    base = os.path.basename(str(name or "")) or fallback
    return re.sub(r"[^\w.\- ]+", "_", base)[:120] or fallback


def _branch(cwd: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, timeout=3)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _estimate_tokens(text: str) -> int:
    return max(0, len(text or "") // 4)


async def handle(gw: "Gateway", method: str, p: dict) -> Any:
    from neovarch.server import RpcError, to_ui_messages

    if method == "session.close":
        sid = str(p.get("session_id") or "")
        live = gw.live.get(sid)
        if live is not None and live.status != "running":
            gw.store.save(live.rec)
            gw.live.pop(sid, None)
        return {"ok": True, "session_id": sid}

    if method == "session.cwd.set":
        live = gw._live(p)
        cwd = Path(os.path.expanduser(str(p.get("cwd") or ""))).resolve()
        if not cwd.is_dir():
            raise RpcError(-32602, f"folder tidak ada: {cwd}")
        live.ctx.cwd = cwd
        live.rec["cwd"] = str(cwd)
        gw.store.save(live.rec)
        info = live.info()
        return {**info, "cwd": str(cwd), "branch": _branch(cwd)}

    if method == "session.history":
        live = gw._live(p)
        return {"session_id": live.id, "messages": to_ui_messages(live.rec)}

    if method == "session.context_breakdown":
        live = gw._live(p)
        from neovarch.agent import system_prompt
        cfg = cfgmod.load_config()
        sys_tokens = _estimate_tokens(system_prompt(cfg, live.ctx.cwd))
        buckets = {"user": 0, "assistant": 0, "tool": 0}
        for m in live.rec.get("messages", []):
            role = m.get("role")
            if role in buckets:
                buckets[role] += _estimate_tokens(str(m.get("content") or ""))
        limit = int(cfgmod.get_path(cfg, "model.context_length", 128000) or 128000)
        items = [{"key": "system", "label": "Instruksi sistem", "tokens": sys_tokens},
                 {"key": "user", "label": "Pesan kamu", "tokens": buckets["user"]},
                 {"key": "assistant", "label": "Jawaban", "tokens": buckets["assistant"]},
                 {"key": "tool", "label": "Hasil alat", "tokens": buckets["tool"]}]
        total = sum(i["tokens"] for i in items)
        return {"session_id": live.id, "total": total, "context_length": limit,
                "percent": round(100 * total / limit, 1) if limit else 0, "items": items, "estimated": True}

    if method in ("image.attach", "image.attach_bytes", "file.attach"):
        live = gw._live(p)
        updir = _uploads_dir(live.id)
        data: bytes | None = None
        name = _safe_name(p.get("filename") or p.get("name") or p.get("path") or "", "lampiran")
        if p.get("content_base64"):
            data = base64.b64decode(str(p["content_base64"]), validate=False)
        elif str(p.get("data_url") or "").startswith("data:") and "," in str(p["data_url"]):
            data = base64.b64decode(str(p["data_url"]).split(",", 1)[1], validate=False)
        src = Path(os.path.expanduser(str(p.get("path") or ""))) if p.get("path") else None
        if data is None:
            if src is None or not src.is_file():
                return {"attached": False, "message": f"File tidak ditemukan: {p.get('path') or name}"}
            if src.stat().st_size > MAX_ATTACH_BYTES:
                return {"attached": False, "message": "File terlalu besar (maks 25 MB)."}
            path = src.resolve()
        else:
            if len(data) > MAX_ATTACH_BYTES:
                return {"attached": False, "message": "File terlalu besar (maks 25 MB)."}
            path = updir / f"{int(time.time() * 1000)}-{name}"
            path.write_bytes(data)
        size = path.stat().st_size
        live.rec.setdefault("attachments", []).append({"path": str(path), "name": name, "ts": time.time()})
        gw.store.save(live.rec)
        ref = f"@file:{path}"
        if method == "file.attach":
            return {"attached": True, "path": str(path), "ref_path": str(path), "ref_text": ref,
                    "uploaded": data is not None, "name": name, "bytes": size}
        return {"attached": True, "path": str(path), "text": ref, "name": name, "bytes": size,
                "count": len(live.rec["attachments"])}

    if method == "image.detach":
        live = gw._live(p)
        target = str(p.get("path") or "")
        before = live.rec.get("attachments") or []
        live.rec["attachments"] = [a for a in before if target and a.get("path") != target]
        gw.store.save(live.rec)
        return {"ok": True, "count": len(live.rec["attachments"])}

    if method in ("session.steer", "prompt.btw"):
        live = gw._live(p)
        text = str(p.get("text") or "").strip()
        if not text:
            raise RpcError(-32602, "text is required")
        if live.status == "running":
            from neovarch import msg_queue
            try:
                it = live.enqueue(text)
            except msg_queue.QueueError as exc:
                raise RpcError(-32602, str(exc)) from None
            return {"ok": True, "status": "queued", "session_id": live.id, "queue_id": it["id"],
                    "queue": live.queue_payload()}
        live.submit(text)
        return {"ok": True, "status": "running", "session_id": live.id}

    if method == "llm.oneshot":
        from neovarch.llm import LLMError, stream_chat
        from neovarch import session_settings
        cfg = cfgmod.load_config()
        ep = session_settings.effective_endpoint(cfg, None)
        prompt = str(p.get("prompt") or p.get("text") or "")
        msgs = [{"role": "system", "content": str(p.get("system") or "Jawab singkat.")},
                {"role": "user", "content": prompt}]
        try:
            comp = await stream_chat(base_url=ep["base_url"], api_key=ep["api_key"], model=ep["model"],
                                     messages=msgs, extra_headers=ep.get("headers") or None,
                                     verify_ssl=ep.get("verify_ssl", True), timeout_s=120)
        except LLMError as exc:
            raise RpcError(-32000, str(exc))
        return {"text": comp.text, "model": ep["model"]}

    if method == "process.stop":
        return {"ok": True, "stopped": False, "message": "Tidak ada proses latar yang berjalan."}

    return NOT_HANDLED
