"""Model routing: the live model list, the global default and per-agent models.

* The list comes live from 9Router's ``GET /v1/models`` (cached 30 s), plus the
  models of any other provider the user configured (presets, custom endpoints).
* The global default is ``model.provider`` + ``model.default`` in config.yaml. A fresh
  install has neither, so it uses the built-in default: provider ``9router`` with an
  OpenCode Free model (``router9.DEFAULT_MODEL``).
* Each Office agent (``session:<id>`` / ``kanban:<name>``) may have its own model in
  ``agents.models``; without one it follows the global default. The override is
  applied to that agent's next turn (``endpoint_for``).
"""

from __future__ import annotations

import copy
import time
from typing import Any

import aiohttp

from neovarch import config as cfgmod
from neovarch import router9

CACHE_S = 30.0
AGENT_PREFIXES = ("session:", "kanban:")


class ModelError(ValueError):
    pass


# ------------------------------------------------------------ default model ---

def default_ref(cfg: dict) -> dict[str, str]:
    provider = str(cfgmod.get_path(cfg, "model.provider", "") or "")
    model = str(cfgmod.get_path(cfg, "model.default", "") or "")
    if provider or cfgmod.get_path(cfg, "model.base_url", ""):
        ep = cfgmod.resolve_endpoint(cfg)
        return {"model": ep["model"], "provider": ep["provider"], "source": "config"}
    return {"model": model or router9.default_model_id(cfg), "provider": router9.PROVIDER, "source": "builtin"}


def set_default(cfg: dict, model: str, provider: str | None = None, known_9router: set[str] | None = None) -> dict:
    model = str(model or "").strip()
    if not model:
        raise ModelError("model wajib diisi")
    prov = str(provider or "").strip()
    if not prov:
        cur = default_ref(cfg)["provider"]
        prov = router9.PROVIDER if (known_9router and model in known_9router) or cur == router9.PROVIDER else cur
    from neovarch import providers
    if prov == router9.PROVIDER:
        providers.activate(cfg, prov, model)
    else:
        providers.set_model(cfg, {"scope": "main", "provider": prov, "model": model})
    return {"model": model, "provider": prov}


# --------------------------------------------------------- per-agent models ---

def normalize_agent_id(raw: str) -> str:
    aid = str(raw or "").strip()
    if not aid:
        raise ModelError("agent_id wajib diisi")
    if not aid.startswith(AGENT_PREFIXES):
        aid = "session:" + aid
    if len(aid) > 200:
        raise ModelError("agent_id terlalu panjang")
    return aid


def _overrides(cfg: dict) -> dict[str, dict]:
    agents = cfg.setdefault("agents", {})
    if not isinstance(agents, dict):
        agents = {}
        cfg["agents"] = agents
    models = agents.setdefault("models", {})
    if not isinstance(models, dict):
        models = {}
        agents["models"] = models
    return models


def overrides(cfg: dict) -> dict[str, dict]:
    raw = cfgmod.get_path(cfg, "agents.models", {}) or {}
    out = {}
    for k, v in raw.items() if isinstance(raw, dict) else []:
        if isinstance(v, str) and v:
            out[str(k)] = {"model": v, "provider": ""}
        elif isinstance(v, dict) and v.get("model"):
            out[str(k)] = {"model": str(v["model"]), "provider": str(v.get("provider") or "")}
    return out


def agent_model(cfg: dict, agent_id: str) -> dict[str, Any]:
    aid = normalize_agent_id(agent_id)
    dflt = default_ref(cfg)
    ov = overrides(cfg).get(aid)
    if ov:
        ref = {"model": ov["model"], "provider": ov["provider"] or dflt["provider"]}
        return {"agent_id": aid, "model": ref["model"], "provider": ref["provider"], "override": ref, "source": "agent"}
    return {"agent_id": aid, "model": dflt["model"], "provider": dflt["provider"], "override": None, "source": "global"}


def set_agent_model(cfg: dict, agent_id: str, model: str | None, provider: str | None = None,
                    known_9router: set[str] | None = None) -> dict[str, Any]:
    aid = normalize_agent_id(agent_id)
    table = _overrides(cfg)
    model = str(model or "").strip()
    if not model:
        table.pop(aid, None)
    else:
        prov = str(provider or "").strip()
        if not prov:
            prov = router9.PROVIDER if known_9router and model in known_9router else default_ref(cfg)["provider"]
        table[aid] = {"model": model, "provider": prov}
    return agent_model(cfg, aid)


def endpoint_for(cfg: dict, agent_id: str | None) -> dict[str, Any]:
    """The endpoint an agent's next turn talks to (its own model, else the global one)."""
    if agent_id:
        try:
            ov = overrides(cfg).get(normalize_agent_id(agent_id))
        except ModelError:
            ov = None
        if ov:
            alt = copy.deepcopy(cfg)
            prov = ov["provider"] or default_ref(cfg)["provider"]
            alt.setdefault("model", {})
            alt["model"]["provider"] = prov
            alt["model"]["default"] = ov["model"]
            if prov != str(cfgmod.get_path(cfg, "model.provider", "") or ""):
                alt["model"]["base_url"] = ""
            return cfgmod.resolve_endpoint(alt)
    return cfgmod.resolve_endpoint(cfg)


# --------------------------------------------------------------- the list -----

def _label(mid: str) -> str:
    name = mid.split("/", 1)[1] if "/" in mid else mid
    return name


def entry_9router(row: dict, default_id: str) -> dict[str, Any]:
    mid = str(row.get("id") or "")
    alias = mid.split("/", 1)[0] if "/" in mid else None
    group = router9.ALIAS_GROUPS.get(alias or "", (alias or "Combo").upper() if alias else "Combo")
    caps = row.get("capabilities") if isinstance(row.get("capabilities"), dict) else {}
    ctx = row.get("context_length") or caps.get("contextWindow")
    return {"id": mid, "label": _label(mid), "provider": router9.PROVIDER, "provider_label": router9.LABEL,
            "group": group, "alias": alias, "free": alias in router9.FREE_ALIASES, "recommended": mid == default_id,
            "context_length": int(ctx) if isinstance(ctx, (int, float)) else None,
            "owned_by": row.get("owned_by")}


class ModelCatalog:
    """Live list of models, cached. ``changed`` is True when a fetch altered the ids."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.fetched_at = 0.0
        self.error: str | None = None

    def ids(self) -> set[str]:
        return {str(r.get("id")) for r in self.rows if r.get("id")}

    async def fetch(self, cfg: dict, force: bool = False) -> bool:
        if not force and self.fetched_at and time.time() - self.fetched_at < CACHE_S:
            return False
        base = router9.base_url(cfg)
        headers = {"Accept": "application/json"}
        key = router9.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        before = self.ids()
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
                async with s.get(base + "/models", headers=headers) as r:
                    if r.status >= 400:
                        self.error = f"9Router membalas HTTP {r.status} untuk daftar model."
                        self.fetched_at = time.time()
                        return False
                    data = await r.json(content_type=None)
        except Exception as exc:  # noqa: BLE001 - shown in the picker
            self.error = f"9Router tidak terjangkau di {base} ({type(exc).__name__})."
            self.rows = []
            self.fetched_at = time.time()
            return bool(before)
        rows = data.get("data") if isinstance(data, dict) else data
        self.rows = [r for r in rows or [] if isinstance(r, dict) and r.get("id")
                     and not r.get("kind")]  # web search/fetch combos are not chat models
        self.error = None
        self.fetched_at = time.time()
        router9.LAST_MODEL_IDS[:] = [str(r["id"]) for r in self.rows]
        try:  # vision flags the upstreams declare (input_modalities, capabilities, …)
            from neovarch import uploads
            uploads.remember_model_meta(self.rows)
        except Exception:  # noqa: BLE001 - metadata is a bonus, never a failure
            pass
        return self.ids() != before

    def listing(self, cfg: dict, router_running: bool) -> list[dict]:
        dflt = default_ref(cfg)
        builtin_default = router9.default_model_id(cfg)
        out = [entry_9router(r, dflt["model"] if dflt["provider"] == router9.PROVIDER else "") for r in self.rows]
        seen = {e["id"] for e in out}
        # The OpenCode Free default works through 9Router even when its /v1/models does
        # not list it (fresh 9Router with no provider connected).
        for mid in [builtin_default] + ([dflt["model"]] if dflt["provider"] == router9.PROVIDER else []):
            if mid and mid not in seen and (router_running or not out):
                out.insert(0, entry_9router({"id": mid, "owned_by": "oc"}, dflt["model"]))
                seen.add(mid)
        # Free and recommended first, then by group and name.
        out.sort(key=lambda e: (not e["recommended"], not e["free"], e["group"].lower(), e["label"].lower()))
        from neovarch import providers
        try:
            opts = providers.model_options(cfg)
        except Exception:  # noqa: BLE001
            opts = {"providers": []}
        for p in opts.get("providers", []):
            if p.get("slug") == router9.PROVIDER:
                continue
            for mid in p.get("models") or []:
                out.append({"id": mid, "label": mid, "provider": p["slug"], "provider_label": p.get("name") or p["slug"],
                            "group": p.get("name") or p["slug"], "alias": None, "free": False,
                            "recommended": dflt["provider"] == p["slug"] and dflt["model"] == mid,
                            "context_length": None, "owned_by": None})
        return out
