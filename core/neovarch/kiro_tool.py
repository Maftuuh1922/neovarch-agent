"""Kiro as a Neovarch tool (Kiroween 2026 entry: Neovarch Agent + Kiro Crew).

The main agent delegates a coding task to Kiro CLI; Kiro works in a disposable
git worktree, never in the real repo. The resulting diff is saved as a *proposal*
under ``~/.neovarch/kiro-proposals/`` and only reaches the real repo when the
user approves ``apply`` — through the existing ``ctx.approve`` gate (the same
one ``shell`` uses: terminal prompt in the CLI, approval card on desktop/phone
in the gateway). Nothing here builds its own approval UI.

How it is wired in: ``tools.py`` registers ``"kiro"`` at the bottom via
``_register_kiro_tools`` (the same pattern as ``design``/``vision``), with the
thin ``_tool_kiro`` wrapper delegating to ``tool_kiro`` + ``TOOL_SCHEMA`` here.
``kiro_tool`` imports its ``tools`` helpers (``_clip``, ``_resolve`` …) lazily
inside the functions that use them — never at module top level — because
``tools`` imports ``kiro_tool`` during its own initialisation; a top-level
import in either direction is a circular import. ``kiro`` is deliberately NOT
in ``READ_ONLY_TOOLS``: it can change files, so it must never be prefetched as
a read-only call, and ``apply`` must pass the approval gate.

Assumptions about Kiro CLI (verified against the official docs,
https://kiro.dev/docs/cli/headless/ and
https://kiro.dev/docs/reference/cli-commands/, November 2026 — do not trust
them blindly, check with ``kiro-cli --help`` when the CLI changes):

* The binary is ``kiro-cli`` (installed from https://cli.kiro.dev/install).
  Resolution order: env ``KIRO_BIN`` first, then ``kiro-cli`` on PATH, then
  ``kiro`` on PATH (a common alias).
* Headless invocation: ``kiro-cli chat --v3 --no-interactive
  --trust-all-tools "<prompt>"``. ``--no-interactive`` runs one prompt and
  exits; the prompt is a positional argument. ``--v3`` pins the harness so a
  change of defaults does not change the run. ``--trust-all-tools`` is
  required: without a trust flag, tool calls that need approval are denied in
  non-interactive mode and the run stalls. The containment for that broad
  trust is the disposable worktree below plus the approval gate on ``apply``.
* Authentication for headless runs is the ``KIRO_API_KEY`` environment
  variable (API keys need a Pro plan or above). This module NEVER reads,
  prints or sends the key — or any other secret. The CLI subprocess simply
  inherits the process environment, i.e. the user's own Kiro auth on their PC.
  Secrets stay in ``~/.neovarch/.env`` and are never passed to Kiro.
* ``KIRO_COMMAND`` (env) overrides the whole command line: a shell-style
  template where ``{prompt}`` is replaced by the instruction (appended at the
  end when the placeholder is absent). Use it when the installed CLI needs
  different flags.
* The CLI is expected to edit files in its working directory and print a short
  summary. It must NOT commit, push or create branches — the prompt says so,
  and the worktree is thrown away after the diff is captured anyway.
* New files are captured with ``git add -N`` (intent-to-add) + ``git diff``,
  so the patch also covers files Kiro created. Binary content is not carried
  by a plain ``git diff``: if Kiro creates binary files, ``git apply --check``
  in ``apply`` refuses the patch and says so instead of applying half of it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shlex
import shutil
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from neovarch.paths import check_path, neovarch_home

if TYPE_CHECKING:  # annotations only; a runtime import here would be circular (tools imports kiro_tool)
    from neovarch.tools import ToolContext

PROPOSALS_DIR = "kiro-proposals"
DEFAULT_TIMEOUT = 600
MIN_TIMEOUT = 10
MAX_TIMEOUT = 3600
DIFF_CHARS = 6000
STEERING_CHARS = 8000

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,64}$")

_INSTALL_HINT = (
    "Kiro CLI tidak ditemukan. Pasang dari https://cli.kiro.dev/install "
    "(curl -fsSL https://cli.kiro.dev/install | bash), pastikan binary `kiro-cli` ada di PATH, "
    "atau set env KIRO_BIN ke path binary-nya. Mode headless juga butuh KIRO_API_KEY "
    "(API key Kiro, paket Pro ke atas); tanpa itu Kiro CLI akan meminta login browser "
    "dan gagal di mode non-interaktif."
)


class KiroError(Exception):
    """User-facing failure of the kiro tool (reported as ``error: ...``)."""


# ------------------------------------------------------------------ helpers --
def resolve_binary() -> str | None:
    """The Kiro CLI binary: KIRO_BIN, then ``kiro-cli``, then ``kiro`` on PATH."""
    explicit = os.environ.get("KIRO_BIN", "").strip()
    if explicit:
        return explicit
    for name in ("kiro-cli", "kiro"):
        found = shutil.which(name)
        if found:
            return found
    return None


def build_command(binary: str, prompt: str) -> list[str]:
    """Headless Kiro CLI invocation (KIRO_COMMAND overrides the template)."""
    template = os.environ.get("KIRO_COMMAND", "").strip()
    if template:
        parts = shlex.split(template)
        if "{prompt}" in parts:
            return [p if p != "{prompt}" else prompt for p in parts]
        return [*parts, prompt]
    return [binary, "chat", "--v3", "--no-interactive", "--trust-all-tools", prompt]


async def _run(argv: list[str], cwd: Path, timeout: float,
               stdin_text: str | None = None) -> tuple[int, str, str]:
    """Run a command, capturing stdout/stderr separately (env inherited)."""
    from neovarch.tools import decode_output  # lazy: tools imports this module at load time
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE if stdin_text is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(stdin_text.encode("utf-8") if stdin_text is not None else None), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except asyncio.TimeoutError:
            pass
        raise KiroError(f"perintah melebihi batas {timeout:.0f} detik dan dihentikan")
    return proc.returncode or 0, decode_output(out or b""), decode_output(err or b"")


async def _git(repo: Path, *args: str, timeout: float = 60,
               stdin_text: str | None = None) -> str:
    rc, out, err = await _run(["git", "-C", str(repo), *args], repo, timeout, stdin_text)
    if rc != 0:
        raise KiroError(f"git {' '.join(args[:2])} gagal: {(err or out).strip()[:500]}")
    return out.strip()


def proposals_dir() -> Path:
    d = neovarch_home() / PROPOSALS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _proposal_id() -> str:
    return "kp" + secrets.token_hex(4)


def _check_id(pid: str) -> str:
    pid = str(pid or "").strip()
    if not _ID_RE.match(pid):
        raise KiroError(f"proposal_id tidak valid: {pid!r}")
    return pid


def _load_proposal(pid: str) -> tuple[dict, Path]:
    pid = _check_id(pid)
    meta_path = proposals_dir() / f"{pid}.json"
    patch_path = proposals_dir() / f"{pid}.patch"
    if not meta_path.exists() or not patch_path.exists():
        raise KiroError(f"proposal {pid} tidak ditemukan (mungkin sudah diterapkan atau dibuang)")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise KiroError(f"metadata proposal {pid} rusak")
    if not isinstance(meta, dict) or meta.get("id") != pid:
        raise KiroError(f"metadata proposal {pid} tidak cocok")
    return meta, patch_path


def _drop_proposal(pid: str) -> None:
    d = proposals_dir()
    for suffix in (".json", ".patch"):
        try:
            (d / f"{pid}{suffix}").unlink(missing_ok=True)
        except OSError:
            pass


def _resolve_in(root: Path, raw: str) -> Path:
    """Resolve ``raw`` against ``root``; refuse anything outside the repo."""
    from neovarch.tools import _inside  # lazy: tools imports this module at load time
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    check_path(p)
    if not _inside(p, root):
        raise KiroError(f"path di luar repo: {raw}")
    return p


async def _repo_root(ctx: ToolContext, raw: str | None) -> Path:
    from neovarch.tools import _resolve  # lazy: tools imports this module at load time
    root = _resolve(ctx, raw or ".")
    if not root.is_dir():
        raise KiroError(f"bukan direktori: {root}")
    rc, _, _ = await _run(["git", "-C", str(root), "rev-parse", "--git-dir"], root, timeout=30)
    if rc != 0:
        raise KiroError(f"bukan repo git: {root} (jalankan `git init` dulu, atau arahkan cwd ke repo)")
    return root


def load_steering(root: Path) -> str:
    """Contents of ``.kiro/steering/*.md`` in the repo ('' when there is none)."""
    from neovarch.tools import _clip  # lazy: tools imports this module at load time
    d = root / ".kiro" / "steering"
    if not d.is_dir():
        return ""
    parts = []
    for f in sorted(d.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if text.strip():
            parts.append(f"### steering/{f.name}\n{text.strip()}")
    if not parts:
        return ""
    return _clip("\n\n".join(parts), STEERING_CHARS)


def build_prompt(task: str, paths: list[str], steering: str) -> str:
    lines = [
        "You are working in a disposable git worktree copy of a repository. "
        "Make the requested changes in this working copy only.",
        "",
        f"Task: {task}",
    ]
    if paths:
        lines += ["", "Target files (create them if they do not exist yet):"] + [f"- {p}" for p in paths]
    if steering:
        lines += ["", "Repo steering (follow these rules):", steering]
    lines += ["",
              "Rules:",
              "- Edit, create, or delete files in this working copy as needed for the task.",
              "- Do NOT commit, do NOT push, do NOT create branches.",
              "- Do NOT touch files outside this working copy.",
              "- When done, print a short summary of what changed."]
    return "\n".join(lines)


async def _ask(ctx: ToolContext, command: str, description: str) -> str | None:
    """Ask through the existing approval gate; error string when denied, else None.

    The agent loop does not gate non-read-only tools by itself — each tool asks
    explicitly (see ``tool_shell``). ``approvals_mode == "off"`` skips asking,
    exactly like the other tools.
    """
    if ctx.approvals_mode == "off":
        return None
    approve = getattr(ctx, "approve", None)
    if approve is None:
        return ("error: tidak bisa meminta persetujuan di sesi ini (approve tidak tersedia); "
                "jalankan dari terminal atau gateway")
    choice = await approve(command, description, "kiro")
    if choice in ("deny", "", None):
        return "denied: the user did not approve this."
    return None


def _timeout(args: dict) -> float:
    try:
        t = float(args.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        t = DEFAULT_TIMEOUT
    return min(max(t, MIN_TIMEOUT), MAX_TIMEOUT)


# ------------------------------------------------------------------ actions --
async def _propose(args: dict, ctx: ToolContext) -> str:
    from neovarch.tools import _clip  # lazy: tools imports this module at load time
    task = str(args.get("task") or "").strip()
    if not task:
        return "error: task is required (apa yang harus dikerjakan Kiro?)"
    timeout = _timeout(args)
    root = await _repo_root(ctx, args.get("cwd"))
    raw_paths = args.get("paths") or []
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    rel_paths = [str(_resolve_in(root, str(raw)).relative_to(root)) for raw in raw_paths]
    base = await _git(root, "rev-parse", "HEAD")
    binary = resolve_binary()
    if binary is None:
        return f"error: {_INSTALL_HINT}"
    denied = await _ask(ctx, f"kiro propose: {task[:120]}",
                        f"Jalankan Kiro CLI untuk tugas ini di salinan sementara repo {root} "
                        f"(worktree; repo asli tidak diubah).")
    if denied:
        return denied
    steering = load_steering(root)
    prompt = build_prompt(task, rel_paths, steering)
    command = build_command(binary, prompt)
    tmp = Path(tempfile.mkdtemp(prefix="neovarch-kiro-"))
    work = tmp / "wt"
    try:
        await _git(root, "worktree", "add", "--detach", str(work), "HEAD")
        rc, out, err = await _run(command, work, timeout)
        if rc != 0:
            detail = (err or out).strip()
            return (f"error: Kiro CLI gagal (exit {rc}).\n"
                    + (_clip(detail, 2000) if detail else "(tanpa output)")
                    + "\nRepo asli tidak diubah.")
        status = await _git(work, "status", "--porcelain")
        if not status.strip():
            summary = out.strip()
            msg = "Kiro selesai tanpa mengusulkan perubahan apa pun (tidak ada diff). Repo asli tidak diubah."
            return msg + (f"\nRingkasan Kiro:\n{_clip(summary, 1000)}" if summary else "")
        await _git(work, "add", "-N", "-A")
        patch = await _git(work, "diff")
        files = await _git(work, "diff", "--name-only")
        if not patch.strip():
            return "Kiro selesai tanpa mengusulkan perubahan apa pun (tidak ada diff). Repo asli tidak diubah."
        pid = _proposal_id()
        d = proposals_dir()
        (d / f"{pid}.patch").write_text(patch if patch.endswith("\n") else patch + "\n", encoding="utf-8")
        meta = {"id": pid, "repo": str(root), "base": base, "task": task[:500],
                "files": [f for f in files.splitlines() if f.strip()], "created": time.time()}
        (d / f"{pid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        files_txt = "\n".join(f"- {f}" for f in meta["files"])
        return (f"Proposal {pid} siap (repo {root}, basis {base[:10]}).\n"
                f"File yang diusulkan berubah:\n{files_txt}\n\n"
                f"Diff (dipotong):\n{_clip(patch, DIFF_CHARS)}\n\n"
                f"Tinjau diff di atas. Untuk menerapkan ke repo asli: kiro apply proposal_id={pid}. "
                f"Untuk membuang: kiro discard proposal_id={pid}. Repo asli belum diubah.")
    finally:
        try:
            await _run(["git", "-C", str(root), "worktree", "remove", "--force", str(work)],
                       root, timeout=60)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


async def _apply(args: dict, ctx: ToolContext) -> str:
    from neovarch.tools import _clip  # lazy: tools imports this module at load time
    pid = str(args.get("proposal_id") or "").strip()
    meta, patch_path = _load_proposal(pid)
    repo = Path(str(meta.get("repo") or ""))
    root = await _repo_root(ctx, str(repo))
    patch = patch_path.read_text(encoding="utf-8")
    files = meta.get("files") or []
    files_txt = ", ".join(files) if files else "(tidak diketahui)"
    denied = await _ask(ctx, f"kiro apply {pid}",
                        f"Terapkan patch Kiro ke {root} ({len(files)} file: {files_txt}).")
    if denied:
        # The user rejected the diff: discard it and report that nothing changed.
        _drop_proposal(pid)
        return f"ditolak pengguna: proposal {pid} dibuang, tidak ada perubahan di repo."
    try:
        head = await _git(root, "rev-parse", "HEAD")
    except KiroError:
        head = ""
    rc, _, check_err = await _run(["git", "-C", str(root), "apply", "--check", "--whitespace=nowarn", "-"],
                                  root, timeout=60, stdin_text=patch)
    if rc != 0:
        return (f"error: patch {pid} tidak bisa diterapkan ke {root} "
                f"(repo mungkin sudah berubah sejak proposal dibuat).\n"
                f"{_clip((check_err or '').strip(), 1000)}\n"
                f"Proposal tetap tersimpan; periksa lalu coba lagi atau buang dengan kiro discard.")
    rc, _, apply_err = await _run(["git", "-C", str(root), "apply", "--whitespace=nowarn", "-"],
                                  root, timeout=60, stdin_text=patch)
    if rc != 0:
        return (f"error: git apply gagal: {_clip((apply_err or '').strip(), 1000)}\n"
                f"Proposal tetap tersimpan.")
    _drop_proposal(pid)
    drift = ""
    if head and meta.get("base") and head != meta["base"]:
        drift = (f"\nCatatan: HEAD repo sudah pindah dari basis proposal "
                 f"({str(meta['base'])[:10]} → {head[:10]}), tapi patch tetap diterapkan bersih.")
    return (f"Diterapkan: proposal {pid} → {root}\nFile berubah:\n"
            + "\n".join(f"- {f}" for f in files) + drift)


async def _discard(args: dict, ctx: ToolContext) -> str:
    pid = str(args.get("proposal_id") or "").strip()
    meta, _ = _load_proposal(pid)
    _drop_proposal(pid)
    return f"Proposal {pid} dibuang; tidak ada perubahan di repo {meta.get('repo')}."


async def _list_specs(args: dict, ctx: ToolContext) -> str:
    root = await _repo_root(ctx, args.get("cwd"))
    specs = root / ".kiro" / "specs"
    if not specs.is_dir():
        return f"(tidak ada .kiro/specs di repo {root})"
    lines = [f"Specs di {root}/.kiro/specs:"]
    for d in sorted(p for p in specs.iterdir() if p.is_dir()):
        files = sorted(f.name for f in d.iterdir() if f.is_file())
        lines.append(f"- {d.name}: " + (", ".join(files) if files else "(kosong)"))
    top = sorted(f.name for f in specs.iterdir() if f.is_file())
    if top:
        lines.append("File di specs/: " + ", ".join(top))
    return "\n".join(lines) if len(lines) > 1 else f"(tidak ada spec di {root}/.kiro/specs)"


TOOL_SCHEMA = {
    "description": ("Kiro: kerjakan tugas coding lewat Kiro CLI dan bawa hasilnya kembali sebagai proposal diff. "
                    "action=propose menjalankan Kiro di salinan sementara (worktree) repo dan menyimpan diff-nya "
                    "sebagai proposal (repo asli TIDAK diubah); action=apply menerapkan proposal yang sudah "
                    "disetujui pengguna ke repo asli (minta persetujuan dulu); action=discard membuang proposal; "
                    "action=list_specs melihat spec .kiro/specs yang ada di repo. Steering .kiro/steering dibaca "
                    "sebagai konteks sebelum propose. Butuh Kiro CLI (kiro-cli) + KIRO_API_KEY di PC ini."),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["propose", "apply", "discard", "list_specs"]},
        "task": {"type": "string", "description": "tugas coding untuk Kiro (wajib untuk propose)"},
        "paths": {"type": "array", "items": {"type": "string"},
                  "description": "file target (relatif ke repo; dibuat bila belum ada)"},
        "cwd": {"type": "string", "description": "repo git target (default: folder kerja saat ini)"},
        "proposal_id": {"type": "string", "description": "id proposal (wajib untuk apply/discard)"},
        "timeout": {"type": "number", "description": "detik maks Kiro CLI berjalan, default 600"}},
        "required": ["action"]},
}


async def tool_kiro(args: dict, ctx: ToolContext) -> str:
    try:
        action = str(args.get("action") or "").strip()
        if action == "propose":
            return await _propose(args, ctx)
        if action == "apply":
            return await _apply(args, ctx)
        if action == "discard":
            return await _discard(args, ctx)
        if action == "list_specs":
            return await _list_specs(args, ctx)
        return "error: action harus propose | apply | discard | list_specs"
    except KiroError as exc:
        return f"error: {exc}"
