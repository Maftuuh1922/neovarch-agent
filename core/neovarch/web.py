"""Web search + fetch for the agent, zero config (Tempest v2).

* ``search(query)`` - DuckDuckGo HTML over plain HTTP first (no key, no browser). When DDG answers with
  its bot page or nothing, Bing HTML is tried, then a headless browser (system Chrome/Edge/Chromium, or
  Playwright's headless shell installed on demand into ``~/.neovarch/tools``), and Wikipedia's search API
  as the last resort. A configured backend (``web.searxng_url``, ``web.brave_api_key`` /
  ``BRAVE_API_KEY``) is tried first when present.
* ``fetch(url)`` - one HTTP GET, readability-style extraction (main/article text, no nav/footer/script),
  JS-shell detection (an app shell with almost no text) -> headless render fallback.
* Both are cached per session for :data:`CACHE_TTL` seconds, and results are clipped *in context* around
  the passages that match the query (``smart_clip``), so Tempest never has to offload them to a file and
  the model never needs an extra read_file round trip.
"""

from __future__ import annotations

import asyncio
import base64
import html as htmlmod
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import aiohttp

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7"}
CACHE_TTL = 600
FETCH_CHARS = 8000        # one web_fetch result (in context)
SEARCH_PAGE_CHARS = 2500  # each page web_search fetches along with the results
HTTP_TIMEOUT = 20

_cache: dict[tuple[str, str], tuple[float, Any]] = {}


# ------------------------------------------------------------------ cache -----

def cache_get(session: str, key: str) -> Any:
    hit = _cache.get((session, key))
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    return None


def cache_put(session: str, key: str, value: Any) -> None:
    if len(_cache) > 500:  # keep it small: drop the oldest half
        for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[:250]:
            _cache.pop(k, None)
    _cache[(session, key)] = (time.monotonic(), value)


def cache_clear() -> None:
    _cache.clear()


# ------------------------------------------------------------- extraction -----

_DROP = re.compile(r"(?is)<(script|style|noscript|svg|template|iframe|nav|header|footer|aside|form|button|select)"
                   r"\b[^>]*>.*?</\1\s*>")
_BLOCK = re.compile(r"(?i)<br\s*/?>|</?(p|div|li|ul|ol|h[1-6]|tr|table|section|article|main|blockquote|pre|dd|dt)\b[^>]*>")
_HIDDEN = re.compile(r"(?is)<([a-z0-9]+)\b[^>]*(?:aria-hidden=\"true\"|hidden(?:=\"[^\"]*\")?\s*>|display:\s*none)[^>]*>.*?</\1>")
_BOILER = re.compile(r"(?i)^(cookie|accept|terima|privacy|kebijakan privasi|subscribe|login|masuk|daftar|share|bagikan|"
                     r"menu|beranda|home|copyright|©|all rights reserved|baca juga|advertisement|iklan)\b")


def _text(fragment: str) -> str:
    t = _BLOCK.sub("\n", fragment)
    t = re.sub(r"(?i)<h([1-6])\b[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmlmod.unescape(t)
    t = re.sub(r"[ \t\r\f\v\u00a0]+", " ", t)
    lines = [ln.strip() for ln in t.split("\n")]
    out: list[str] = []
    for ln in lines:
        if not ln:
            if out and out[-1]:
                out.append("")
            continue
        if len(ln) < 40 and _BOILER.match(ln):
            continue
        out.append(ln)
    return "\n".join(out).strip()


def title_of(html: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    return re.sub(r"\s+", " ", htmlmod.unescape(m.group(1))).strip()[:200] if m else ""


def extract_readable(html: str) -> tuple[str, str]:
    """(title, main text) of an HTML page: the <article>/<main> part when it holds most of the text."""
    title = title_of(html)
    body = re.sub(r"(?is)<!--.*?-->", " ", html or "")
    body = re.sub(r"(?is)<head\b.*?</head>", " ", body)
    body = _DROP.sub(" ", body)
    body = _HIDDEN.sub(" ", body)
    full = _text(body)
    best = ""
    for pat in (r"(?is)<article\b[^>]*>(.*?)</article>", r"(?is)<main\b[^>]*>(.*?)</main>",
                r"(?is)<[a-z]+\b[^>]*role=\"main\"[^>]*>(.*)"):
        parts = [_text(m.group(1)) for m in re.finditer(pat, body)]
        cand = "\n\n".join(p for p in parts if p)
        if len(cand) > len(best):
            best = cand
    # Prefer the main part only when it really is the content (not a teaser box).
    text = best if best and len(best) >= 0.35 * len(full) and len(best) >= 300 else full
    return title, text


def looks_js_shell(html: str, text: str) -> bool:
    """An app shell that needs JavaScript: almost no readable text for a lot of markup / a root div."""
    t = len((text or "").strip())
    if t >= 1500:
        return False
    markup = len(html or "")
    if t < 200:
        return True
    if markup and t / markup < 0.02 and re.search(r"(?i)<script\b", html or ""):
        return True
    return bool(re.search(r'(?i)id="(__next|root|app|__nuxt|svelte)"', html or "")) and t < 600


# ------------------------------------------------------------ smart clip -----

_STOP = {"yang", "dan", "di", "ke", "dari", "untuk", "the", "of", "a", "an", "in", "on", "is", "what", "how",
         "berapa", "apa", "siapa", "kapan", "dengan", "atau", "to", "for", "and", "or", "by", "with"}


def terms(query: str) -> list[str]:
    return [w for w in re.findall(r"[\w]+", (query or "").lower()) if len(w) > 1 and w not in _STOP][:12]


def smart_clip(text: str, query: str = "", limit: int = FETCH_CHARS) -> str:
    """Keep ``text`` in context within ``limit`` chars: the head plus the paragraphs that best match
    ``query`` (in page order), instead of moving it to a file. Without a query: head + tail."""
    text = text or ""
    if len(text) <= limit:
        return text
    words = terms(query)
    head_n = min(1200, limit // 4)
    head = text[:head_n]
    if not words:
        tail_n = limit - head_n - 80
        return head + f"\n… [{len(text) - head_n - tail_n} karakter dilewati] …\n" + text[-tail_n:]
    paras = [p for p in re.split(r"\n\s*\n|\n(?=[A-Z0-9•\-])", text[head_n:]) if p.strip()]
    scored = []
    for i, p in enumerate(paras):
        low = p.lower()
        hits = sum(low.count(w) for w in words)
        distinct = sum(1 for w in words if w in low)
        num = 1 if re.search(r"\d", p) else 0
        if hits:
            scored.append((distinct * 3 + min(hits, 6) + num, i))
    budget = limit - head_n - 120
    keep: set[int] = set()
    for _, i in sorted(scored, reverse=True):
        size = len(paras[i]) + 2
        if size > budget:
            if budget > 300:  # a long matching block: keep its first part
                paras[i] = paras[i][:budget - 10] + " …"
                keep.add(i)
            break
        keep.add(i)
        budget -= size
    if not keep:
        tail_n = limit - head_n - 80
        return head + f"\n… [{len(text) - head_n - tail_n} karakter dilewati] …\n" + text[-tail_n:]
    out, last = [head], -1
    for i in sorted(keep):
        if i != last + 1:
            out.append("…")
        out.append(paras[i].strip())
        last = i
    dropped = len(text) - sum(len(x) for x in out)
    return "\n\n".join(out) + f"\n\n… [{max(dropped, 0)} karakter lain di halaman ini tidak relevan dengan kueri]"


# ------------------------------------------------------------------- HTTP -----

async def http_get(url: str, *, data: dict | None = None, timeout: float = HTTP_TIMEOUT) -> tuple[int, str, str]:
    """(status, content-type, body). POST when ``data`` is given."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout), headers=HEADERS) as s:
        method = s.post if data is not None else s.get
        async with method(url, data=data, allow_redirects=True) as r:
            raw = await r.read()
            ctype = r.headers.get("Content-Type", "")
            charset = r.charset or "utf-8"
            try:
                body = raw[:3_000_000].decode(charset, errors="replace")
            except LookupError:
                body = raw[:3_000_000].decode("utf-8", errors="replace")
            return r.status, ctype, body


# ------------------------------------------------------------------ search -----

def _strip(x: str) -> str:
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", "", x or ""))).strip()


def _ddg_url(href: str) -> str:
    href = htmlmod.unescape(href or "")
    if href.startswith("//"):
        href = "https:" + href
    q = parse_qs(urlparse(href).query)
    if "uddg" in q:
        return unquote(q["uddg"][0])
    return href


def parse_ddg(html: str) -> list[dict]:
    out = []
    for m in re.finditer(r'(?is)<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>(.*?)'
                         r'(?=<a[^>]+class="[^"]*result__a|$)', html or ""):
        url = _ddg_url(m.group(1))
        if "duckduckgo.com/y.js" in url or not url.startswith("http"):
            continue  # ads
        snip = re.search(r'(?is)class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|td|div)>', m.group(3))
        out.append({"title": _strip(m.group(2)), "url": url, "snippet": _strip(snip.group(1)) if snip else ""})
    if not out:  # lite.duckduckgo.com layout
        for m in re.finditer(r"(?is)<a[^>]+class=['\"]result-link['\"][^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>"
                             r"(.*?)(?=class=['\"]result-link|$)", html or ""):
            snip = re.search(r"(?is)class=['\"]result-snippet['\"][^>]*>(.*?)</td>", m.group(3))
            out.append({"title": _strip(m.group(2)), "url": _ddg_url(m.group(1)),
                        "snippet": _strip(snip.group(1)) if snip else ""})
    return out


def _bing_url(href: str) -> str:
    href = htmlmod.unescape(href or "")
    if "bing.com/ck/a" in href:
        u = parse_qs(urlparse(href).query).get("u", [""])[0]
        if u.startswith("a1"):
            raw = u[2:]
            try:
                return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")
            except (ValueError, UnicodeDecodeError):
                return href
    return href


def parse_bing(html: str) -> list[dict]:
    out = []
    for m in re.finditer(r'(?is)<li class="b_algo"(.*?)</li>', html or ""):
        b = m.group(1)
        a = re.search(r'(?is)<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b)
        if not a:
            continue
        p = re.search(r'(?is)<p[^>]*>(.*?)</p>', b) or re.search(r'(?is)class="b_caption"[^>]*>(.*?)</div>', b)
        out.append({"title": _strip(a.group(2)), "url": _bing_url(a.group(1)), "snippet": _strip(p.group(1)) if p else ""})
    return out


def blocked(status: int, html: str) -> bool:
    return status in (202, 403, 429) or bool(re.search(r"(?i)anomaly-modal|captcha|unusual traffic", html or ""))


def relevant(results: list[dict], query: str) -> bool:
    """At least one result mentions a query term (Bing's bot page returns unrelated filler)."""
    words = [w for w in terms(query) if not w.isdigit()] or terms(query)
    if not words:
        return bool(results)
    need = 1 if len(words) < 3 else 2
    for r in results:
        low = (r.get("title", "") + " " + r.get("snippet", "") + " " + r.get("url", "")).lower()
        if sum(1 for w in words if w in low) >= need:
            return True
    return False


async def _ddg_http(query: str) -> list[dict]:
    st, _, body = await http_get("https://html.duckduckgo.com/html/", data={"q": query, "b": "", "kl": ""})
    res = [] if blocked(st, body) else parse_ddg(body)
    if res:
        return res
    st, _, body = await http_get("https://lite.duckduckgo.com/lite/?q=" + quote_plus(query))
    return [] if blocked(st, body) else parse_ddg(body)


async def _bing_http(query: str) -> list[dict]:
    st, _, body = await http_get("https://www.bing.com/search?q=" + quote_plus(query))
    return [] if st >= 400 else parse_bing(body)


async def _searxng(base: str, query: str) -> list[dict]:
    import json
    st, _, body = await http_get(base.rstrip("/") + "/search?format=json&q=" + quote_plus(query))
    if st >= 400:
        return []
    data = json.loads(body)
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in data.get("results", [])]


async def _brave(key: str, query: str) -> list[dict]:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)) as s:
        async with s.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": 10},
                         headers={"X-Subscription-Token": key, "Accept": "application/json"}) as r:
            if r.status >= 400:
                return []
            data = await r.json()
    return [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": _strip(x.get("description", ""))}
            for x in (data.get("web") or {}).get("results", [])]


async def _wikipedia(query: str) -> list[dict]:
    import json
    lang = "id" if re.search(r"(?i)\b(yang|dan|kota|berapa|apa|siapa|tahun)\b", query) else "en"
    out = []
    for lg in dict.fromkeys([lang, "en"]):
        st, _, body = await http_get(f"https://{lg}.wikipedia.org/w/api.php?action=query&list=search&format=json"
                                     f"&srlimit=5&srsearch=" + quote_plus(query))
        if st >= 400:
            continue
        for r in json.loads(body).get("query", {}).get("search", []):
            out.append({"title": r["title"], "url": f"https://{lg}.wikipedia.org/wiki/" + quote_plus(r["title"].replace(" ", "_")),
                        "snippet": _strip(r.get("snippet", ""))})
        if out:
            break
    return out


async def search(query: str, cfg_get=None, *, session: str = "", n: int = 6) -> tuple[list[dict], str]:
    """(results, backend name). Each backend failing/blocked/irrelevant falls through to the next."""
    query = (query or "").strip()
    key = "search:" + query.lower()
    hit = cache_get(session, key)
    if hit is not None:
        return hit[0][:n], hit[1] + " (cache)"
    get = cfg_get or (lambda k, d=None: d)
    chain: list[tuple[str, Any]] = []
    searx = str(get("web.searxng_url", "") or os.environ.get("SEARXNG_URL", "")).strip()
    brave = str(get("web.brave_api_key", "") or os.environ.get("BRAVE_API_KEY", "")).strip()
    if searx:
        chain.append(("searxng", lambda: _searxng(searx, query)))
    if brave:
        chain.append(("brave", lambda: _brave(brave, query)))
    chain += [("duckduckgo", lambda: _ddg_http(query)), ("bing", lambda: _bing_http(query))]
    browser_note = ""
    if str(get("web.browser", "auto") or "auto").lower() not in ("off", "never", "false"):
        if browser_ready():
            chain.append(("browser", lambda: browser_search(query)))
        else:  # never block a search on a download: install in the background, use it next time
            browser_note = start_browser_install()
    chain.append(("wikipedia", lambda: _wikipedia(query)))
    tried = [browser_note] if browser_note else []
    for name, fn in chain:
        try:
            res = await fn()
        except Exception as exc:  # a backend down is just the next one's turn
            tried.append(f"{name}: {type(exc).__name__}")
            continue
        res = _dedupe(res)
        if res and (name == "wikipedia" or relevant(res, query)):
            cache_put(session, key, (res, name))
            return res[:n], name
        tried.append(f"{name}: kosong")
    return [], "tidak ada (" + "; ".join(tried) + ")"


def _dedupe(results: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in results or []:
        u = (r.get("url") or "").split("#")[0]
        if not u.startswith("http") or u in seen:
            continue
        seen.add(u)
        out.append({**r, "url": u})
    return out


# ------------------------------------------------------------------- fetch -----

async def fetch(url: str, *, session: str = "", render: str = "auto", cfg_get=None) -> dict:
    """{url, status, title, text, rendered, error}. ``render``: auto | always | never."""
    key = f"fetch:{render}:{url}"
    hit = cache_get(session, key)
    if hit is not None:
        return {**hit, "cached": True}
    get = cfg_get or (lambda k, d=None: d)
    browser_ok = str(get("web.browser", "auto") or "auto").lower() not in ("off", "never", "false")
    if browser_ok and not browser_ready():
        browser_ok = False
        if render == "always" or render == "auto":
            out_note = start_browser_install()
        else:
            out_note = ""
    else:
        out_note = ""
    out: dict[str, Any] = {"url": url, "status": 0, "title": "", "text": "", "rendered": False, "error": ""}
    html = ""
    if render != "always":
        try:
            st, ctype, body = await http_get(url)
            out["status"] = st
            if "html" in ctype or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
                html = body
                out["title"], out["text"] = extract_readable(body)
            else:
                out["text"] = body
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    need = render == "always" or (render == "auto" and browser_ok and (
        (html and looks_js_shell(html, out["text"])) or (out["status"] in (403, 429, 503) and not out["text"].strip())
        or (out["error"] and not out["text"])))
    if need:
        try:
            rhtml = await browser_html(url)
            title, text = extract_readable(rhtml)
            if len(text) > len(out["text"]):
                out.update(title=title or out["title"], text=text, rendered=True, error="", status=out["status"] or 200)
        except Exception as exc:
            if not out["text"]:
                out["error"] = (out["error"] + "; " if out["error"] else "") + f"render: {type(exc).__name__}: {exc}"[:200]
    if out_note and (not out["text"] or (html and looks_js_shell(html, out["text"]))):
        out["note"] = out_note  # the page likely needs JS; the renderer is being installed for next time
    if out["text"] and not out["error"]:
        cache_put(session, key, out)
    return out


# ----------------------------------------------------------------- browser -----

_browser_lock = asyncio.Lock()
_pw: Any = None
_browser: Any = None
_idle_task: asyncio.Task | None = None
IDLE_SECONDS = 120
CHROME_ARGS = ["--disable-gpu", "--disable-dev-shm-usage", "--no-zygote", "--renderer-process-limit=2",
               "--js-flags=--max-old-space-size=256", "--no-first-run", "--mute-audio"]


def tools_dir() -> Path:
    from neovarch.paths import neovarch_home
    return neovarch_home() / "tools"


def system_browser() -> str | None:
    """A Chrome/Edge/Chromium already on this PC (so nothing needs downloading)."""
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
                 "microsoft-edge-stable", "brave-browser"):
        p = shutil.which(name)
        if p:
            return p
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")):
        if p and os.path.exists(p):
            return p
    return None


_install_task: "asyncio.Task | None" = None
_install_error = ""


def _tools_site() -> Path:
    return tools_dir() / "py"


def browser_ready() -> bool:
    """Playwright importable and a browser to drive (system Chrome/Edge/Chromium or the installed shell)."""
    import importlib.util
    import sys
    site = str(_tools_site())
    if site not in sys.path and Path(site).is_dir():
        sys.path.insert(0, site)
    try:
        if importlib.util.find_spec("playwright") is None:
            return False
    except (ImportError, ValueError):
        return False
    if system_browser():
        return True
    shells = tools_dir() / "ms-playwright"
    return shells.is_dir() and any(d.name.startswith("chromium") for d in shells.iterdir())


def start_browser_install() -> str:
    """Kick off the one-time Playwright (+ headless shell) install in the background; a note for the result."""
    global _install_task
    if _install_error:
        return f"browser: pemasangan gagal ({_install_error[:80]})"
    if _install_task is not None and not _install_task.done():
        return "browser: sedang dipasang di latar belakang"

    async def go() -> None:
        global _install_error
        try:
            await _ensure_playwright()
            if not system_browser():
                await _install_headless_shell()
        except Exception as exc:  # remembered: no retry storm in this process
            _install_error = f"{type(exc).__name__}: {exc}"

    try:
        _install_task = asyncio.get_running_loop().create_task(go())
    except RuntimeError:
        return "browser: belum terpasang"
    return "browser: belum terpasang, dipasang di latar belakang untuk pencarian berikutnya"


async def _ensure_playwright() -> Any:
    """Import playwright, installing it into ~/.neovarch/tools/py on first use."""
    import importlib
    import sys
    site = tools_dir() / "py"
    if str(site) not in sys.path:
        sys.path.insert(0, str(site))
    try:
        return importlib.import_module("playwright.async_api")
    except ImportError:
        pass
    site.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "pip", "install", "-q", "--target", str(site),
                                                "playwright", stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.PIPE)
    _, err = await asyncio.wait_for(proc.communicate(), 300)
    if proc.returncode != 0:
        raise RuntimeError("pip install playwright gagal: " + err.decode("utf-8", "replace")[-200:])
    importlib.invalidate_caches()
    return importlib.import_module("playwright.async_api")


async def _install_headless_shell() -> None:
    import sys
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(tools_dir() / "ms-playwright"),
           "PYTHONPATH": str(tools_dir() / "py")}
    proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "playwright", "install", "--only-shell",
                                                "chromium", env=env, stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.PIPE)
    _, err = await asyncio.wait_for(proc.communicate(), 600)
    if proc.returncode != 0:
        raise RuntimeError("playwright install gagal: " + err.decode("utf-8", "replace")[-200:])


async def _get_browser() -> Any:
    global _pw, _browser
    if _browser is not None and _browser.is_connected():
        return _browser
    api = await _ensure_playwright()
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(tools_dir() / "ms-playwright"))
    if _pw is None:
        _pw = await api.async_playwright().start()
    exe = system_browser()
    try:
        _browser = await _pw.chromium.launch(headless=True, executable_path=exe, args=CHROME_ARGS)
    except Exception:
        if exe:
            raise
        await _install_headless_shell()
        _browser = await _pw.chromium.launch(headless=True, args=CHROME_ARGS)
    return _browser


def _schedule_idle_close() -> None:
    global _idle_task

    async def close_later() -> None:
        global _browser, _pw
        await asyncio.sleep(IDLE_SECONDS)
        async with _browser_lock:
            try:
                if _browser is not None:
                    await _browser.close()
                if _pw is not None:
                    await _pw.stop()
            finally:
                _browser, _pw = None, None

    if _idle_task is not None:
        _idle_task.cancel()
    try:
        _idle_task = asyncio.get_running_loop().create_task(close_later())
    except RuntimeError:
        _idle_task = None


async def browser_html(url: str, timeout_ms: int = 25000) -> str:
    """The rendered HTML of ``url`` (images/fonts/media blocked)."""
    async with _browser_lock:
        browser = await _get_browser()
        ctx = await browser.new_context(user_agent=UA, locale="id-ID")
        try:
            page = await ctx.new_page()

            async def block(route):
                if route.request.resource_type in ("image", "font", "media"):
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", block)
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                await page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            return await page.content()
        finally:
            await ctx.close()
            _schedule_idle_close()


async def browser_search(query: str) -> list[dict]:
    html = await browser_html("https://html.duckduckgo.com/html/?q=" + quote_plus(query))
    res = parse_ddg(html)
    if res:
        return res
    return parse_bing(await browser_html("https://www.bing.com/search?q=" + quote_plus(query)))


# ------------------------------------------------------------ tool output -----

def format_page(page: dict, query: str, limit: int) -> str:
    head = f"URL: {page['url']}"
    if page.get("title"):
        head += f"\nJudul: {page['title']}"
    flags = [x for x in ("dirender browser" if page.get("rendered") else "", "cache" if page.get("cached") else "") if x]
    if page.get("status"):
        head += f"\nHTTP {page['status']}" + (f" ({', '.join(flags)})" if flags else "")
    if page.get("note"):
        head += f"\n({page['note']}; halaman ini mungkin butuh JavaScript)"
    if page.get("error") and not page.get("text"):
        return head + f"\nerror: {page['error']}"
    return head + "\n\n" + smart_clip(page.get("text", ""), query, limit)
