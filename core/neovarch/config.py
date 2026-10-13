"""config.yaml + .env under the Neovarch home.

Shape (all keys optional)::

    model:
      default: gpt-4o-mini          # model id sent to the provider
      provider: openai              # "9router" (built-in default), a preset, a name from
                                    # `providers:` / `custom_providers:`, or "custom"
      base_url: https://api.openai.com/v1
      context_length: 128000
    providers:                      # named OpenAI-compatible endpoints
      openai: {base_url: https://api.openai.com/v1, key_env: OPENAI_API_KEY}
    custom_providers:               # list form, also accepted
      - {name: Mock, base_url: http://127.0.0.1:9999/v1, key_env: OPENAI_API_KEY}
    approvals:
      mode: ask                     # ask | off  (off = never ask, run everything)
    agent:
      max_turns: 150                # checkpoint: a turn still making progress continues past it (see turn_budget.py)
      system_prompt: ""             # extra instructions appended to SOUL.md
      harness_mode: tempest         # tempest (default when unset) | legacy  (old loop, kept; see tempest.py; "tempa" = old alias)
      tempest_profile: ringan       # ringan | tinggi | otomatis   (only when Tempest runs)
    memory:
      obsidian_vault: ""            # folder of an Obsidian vault used as long-term memory
      obsidian_enabled: true        # false = keep the path but stop using the vault
      vault_autonotes: true         # keep projects, sessions and changed files as linked notes under Neovarch/
    extras:
      auto_install: true            # install missing optional extras (Obsidian) on install/update; never bundled
      obsidian: true                # false = never auto-install Obsidian (the built-in graph works without it)
    appearance:
      accent: "#EE1C1C"             # accent colour chosen at first run (desktop + phone)
      base: dark                    # dark | light
    router9:                        # the built-in 9Router provider (see router9.py)
      base_url: http://localhost:20128/v1
      autostart: true               # start the local 9router when installed and not running
    agents:
      models:                       # per-agent model (Office desk id -> model)
        "session:abc123": {model: oc/big-pickle, provider: 9router}

API keys live in ``.env`` (KEY=value lines), never in config.yaml.
"""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml

from neovarch.paths import neovarch_home

PRESETS: dict[str, dict[str, str]] = {
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY", "model": "gpt-4o-mini"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY", "model": "openai/gpt-4o-mini"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY", "model": "llama-3.3-70b-versatile"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "key_env": "DEEPSEEK_API_KEY", "model": "deepseek-chat"},
    "ollama": {"base_url": "http://127.0.0.1:11434/v1", "key_env": "", "model": "llama3.1"},
}

DEFAULTS: dict[str, Any] = {
    "model": {"default": "", "provider": "", "base_url": "", "context_length": 128000},
    "providers": {},
    "custom_providers": [],
    "approvals": {"mode": "ask"},
    "agent": {"max_turns": 150, "system_prompt": ""},
    # Settings › Obrolan › Perilaku and Ruang kerja › Proyek / Shell / File
    "timezone": "",
    "display": {"show_reasoning": True},
    "terminal": {"cwd": "", "timeout": 60},
    "file_read_max_chars": 20000,
    "memory": {"obsidian_vault": "", "obsidian_enabled": True, "vault_autonotes": True},
    "extras": {"auto_install": True, "obsidian": True},
    "appearance": {"accent": "#EE1C1C", "base": "dark"},
    # Remote HP: a paired phone not seen for this many days is unpaired (0 = never).
    "remote": {"pairing_idle_days": 30},
}

DEFAULT_SOUL = """You are Neovarch Agent, an AI agent from NeovarchLabs that works on the user's own computer.
You can run shell commands, read, write and edit files, fetch web pages, keep memory notes and use skills.
Be direct and concise. Report what you changed and what you verified. Ask before anything destructive.
"""


def config_path() -> Path:
    return neovarch_home() / "config.yaml"


def env_path() -> Path:
    return neovarch_home() / ".env"


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict[str, Any]:
    p = config_path()
    data: dict[str, Any] = {}
    if p.exists():
        loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    cfg = _merge(DEFAULTS, data)
    from neovarch.session_settings import repair_config
    repair_config(cfg)
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    os.replace(tmp, p)


def get_path(cfg: dict, dotted: str, default=None):
    cur: Any = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_path(cfg: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = cfg
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


# ------------------------------------------------------------------ .env -----

def read_env_file() -> dict[str, str]:
    p = env_path()
    out: dict[str, str] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def write_env_value(key: str, value: str) -> None:
    p = env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    lines = [ln for ln in lines if not ln.strip().startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def secret(key: str) -> str:
    if not key:
        return ""
    return os.environ.get(key) or read_env_file().get(key, "")


# ------------------------------------------------------------- providers -----

def provider_entries(cfg: dict) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for name, spec in (cfg.get("providers") or {}).items():
        if isinstance(spec, dict):
            entries[str(name)] = spec
    for spec in cfg.get("custom_providers") or []:
        if isinstance(spec, dict) and (spec.get("id") or spec.get("name")):
            entries[str(spec.get("id") or spec["name"])] = spec
            if spec.get("name") and str(spec["name"]) not in entries:
                entries[str(spec["name"])] = spec
            # The id the desktop uses (custom:<slug>) for an entry written by hand.
            slug = re.sub(r"[^a-z0-9]+", "-", str(spec.get("name") or "").lower()).strip("-")[:48]
            if slug and slug not in entries:
                entries[slug] = spec
    return entries


def endpoint_headers(spec: dict) -> dict[str, str]:
    """Custom HTTP headers of an endpoint. Values live in .env (they can be secrets)."""
    import json as _json
    env = str(spec.get("headers_env") or "")
    raw = secret(env) if env else ""
    out: dict[str, str] = {}
    if raw:
        try:
            data = _json.loads(raw)
            if isinstance(data, dict):
                out = {str(k): str(v) for k, v in data.items()}
        except ValueError:
            pass
    return out


def resolve_endpoint(cfg: dict) -> dict[str, str]:
    """The endpoint the agent talks to: {base_url, api_key, model, provider}."""
    model_cfg = cfg.get("model") or {}
    provider = str(model_cfg.get("provider") or "")
    entries = provider_entries(cfg)
    spec: dict = {}
    if not provider and not model_cfg.get("base_url"):
        # Fresh install: the built-in default provider is the local 9Router.
        provider = "9router"
    if provider.startswith("custom:"):
        spec = entries.get(provider.split(":", 1)[1], {})
    elif provider == "9router" and provider not in entries:
        from neovarch import router9
        spec = router9.endpoint_spec(cfg)
    elif provider in entries:
        spec = entries[provider]
    elif provider in PRESETS:
        spec = PRESETS[provider]
    base_url = str(model_cfg.get("base_url") or spec.get("base_url") or "")
    if not base_url and provider == "custom" and entries:
        spec = next(iter(entries.values()))
        base_url = str(spec.get("base_url") or "")
    key_env = str(spec.get("key_env") or ("OPENAI_API_KEY" if base_url else ""))
    api_key = secret(key_env) or str(spec.get("api_key") or "")
    if not api_key and provider != "9router":
        api_key = secret("NEOVARCH_API_KEY") or secret("OPENAI_API_KEY")
    return {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "model": str(model_cfg.get("default") or spec.get("model") or ""),
        "provider": provider or "custom",
        "headers": endpoint_headers(spec) if spec else {},
        "verify_ssl": not bool(spec.get("allow_insecure_tls")) if spec else True,
    }


def soul_text() -> str:
    p = neovarch_home() / "SOUL.md"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(DEFAULT_SOUL, encoding="utf-8")
    return p.read_text(encoding="utf-8")
