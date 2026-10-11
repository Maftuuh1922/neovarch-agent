# Neovarch core

The agent "brain" of Neovarch Agent: original Python code (MIT), about 2,000
lines, two dependencies (`aiohttp`, `PyYAML`). It runs the chat loop with tool
calling, keeps sessions, memory notes and skills under `~/.neovarch`, and serves
the desktop app and the phone remote through `neovarch serve`.

Design and wire protocol are inspired by [Hermes Agent](https://github.com/NousResearch/hermes-agent)
(Nous Research). No Hermes Agent code is included; see `../NOTICE`.

## Layout

| Module | What it does |
|---|---|
| `neovarch/paths.py` | `~/.neovarch` (or `$NEOVARCH_HOME`, `%LOCALAPPDATA%\neovarch`) and the guard that refuses every file operation on Hermes paths (`~/.hermes`, `~/.local/bin/hermes*`, `~/.local/state/hermes`) |
| `neovarch/config.py` | `config.yaml` + `.env` (API keys), provider presets, endpoint resolution, `SOUL.md` |
| `neovarch/llm.py` | streaming client for any OpenAI-compatible `/chat/completions` (text, reasoning, tool calls) |
| `neovarch/tools.py` | `shell`, `read_file`, `write_file`, `edit_file`, `web_fetch`, `memory`, `skill`; dangerous commands go through approval |
| `neovarch/obsidian.py` | Obsidian vault memory: `obsidian_search` / `obsidian_read` / `obsidian_write` / `obsidian_links`, keyword injection into the system prompt; every path must stay inside the vault |
| `neovarch/office.py` | the Office: agents as "pegawai" derived from live/recent sessions and Kanban assignees, plus an activity feed |
| `neovarch/store.py` | sessions (`sessions/<id>.json`) and the Kanban board (`kanban.json`) |
| `neovarch/agent.py` | the loop: stream, run tools, repeat; emits events |
| `neovarch/server.py` | `neovarch serve`: HTTP + WebSocket gateway for the desktop and phone |
| `neovarch/cli.py` | `neovarch` command line |
| `neovarch/tui/` | the interactive terminal chat (rich + prompt_toolkit): splash, header, slash commands, tool chips, Bukti, approvals |

## Commands

```
neovarch                      # interactive chat in the terminal
neovarch -q "prompt"          # one prompt, then exit
neovarch setup                # choose a provider (openai, openrouter, groq, deepseek, ollama, custom)
neovarch config [show|get|set|path] [key] [value]
neovarch sessions [list|show|delete] [id]
neovarch serve [--host 127.0.0.1] [--port 9319] [--isolated]
neovarch uninstall [--yes]    # removes ~/.neovarch only
neovarch --version
```

`python -m neovarch …` is the same as `neovarch …` (the desktop uses this form).

## Terminal chat (TUI)

`neovarch` with no arguments on a terminal opens the interactive chat: the star
mark and NEOVARCH wordmark, a header (model, reasoning level, connection), streamed
Markdown with syntax highlighting, tool-call chips with a spinner, a collapsible
**Bukti** section (`/bukti`, Ctrl+O) and clickable file paths (OSC 8; `/buka <n>`
opens one). Risky commands ask for approval (once / this session / deny).

| Command | |
|---|---|
| `/baru` | new chat |
| `/model [name] [--global]` | list or switch the model (this chat by default) |
| `/reasoning [rendah\|sedang\|tinggi\|ultra\|mati]` | reasoning level |
| `/skill [name] [message]` | list skills or ask the agent to use one |
| `/stop` | stop the running turn (Ctrl+C does the same) |
| `/status` | model, reasoning, connection, session |
| `/bantuan`, `/keluar` | help, quit |

Keys: Enter sends, Alt+Enter / Ctrl+J (or a trailing `\`) adds a line, ↑/↓ history
(`~/.neovarch/cli_history`), Tab completes commands.

The TUI is a client of the gateway's JSON-RPC session API (`session.create`,
`prompt.submit`, `config.set model|reasoning`, `approval.respond`, …), the same calls
the desktop and phone make. By default the gateway runs in-process; `--connect
http://127.0.0.1:9319 --token <token>` uses a running `neovarch serve` instead.

`--plain`, `NEOVARCH_PLAIN=1`, `TERM=dumb`, or a pipe on stdin/stdout keep plain text
output (no splash, colours or prompt markers). `NO_COLOR` or a terminal narrower than
80 columns shows the monochrome wordmark only. The star mark is a static text asset
(`neovarch/tui/assets/`), regenerated with `scripts/make_logo_ascii.py` (needs Pillow,
developer-only).

## Gateway (`neovarch serve`)

* Prints `HERMES_BACKEND_READY port=<n>` when listening (the readiness line the desktop waits for).
* Auth: the desktop hands the gateway a per-launch session token; clients send it as
  `Authorization: Bearer`, `X-Hermes-Session-Token` / `X-Neovarch-Session-Token` or `?token=`. Remote mode
  (`--isolated` with a signing secret from the desktop) accepts the phone's HMAC-signed access token
  (see `../docs/remote-protocol.md`). Without any token the gateway mints one and prints it; it never runs open.
* `/api/ws`: JSON-RPC 2.0. Implemented: `ping`, `client.capabilities`,
  `session.list|active_list|create|resume|activate|status|title|save|interrupt`, `prompt.submit`,
  `approval.pending|respond`, `config.get|set`, `commands.catalog`, `profiles.list`, and the desktop's boot
  checks `setup.status`, `setup.runtime_check`, `model.options` (answered from `config.yaml`), plus "off"
  answers for features the core does not have (`pet.info`, `free_tier.status`, `wake.status`, `projects.tree`,
  `subagent.list`, `billing.state`, `plugins.manage`, …). Session info carries `desktop_contract` (the
  desktop session-protocol level this core speaks).
* REST: `/api/health`, `/api/status`, sessions, config, model info/options/set, skills, toolsets, profiles,
  Kanban (`/api/plugins/kanban/*`), a small read-only file browser (`/api/fs/*`).
* Features the core does not implement (voice, image generation, OAuth providers, MCP,
  webhooks, plugins, messaging platforms) answer with empty lists, so the desktop shows them empty instead of
  failing. Any other unknown call is answered with 404 / JSON-RPC `-32601` and logged to `logs/unhandled.log`.

## Office, Obsidian memory and appearance

* `GET /api/office` returns a snapshot: `agents[]` (name, role, status `idle` /
  `working` / `waiting-approval`, `current_task`, `current_tool`, `last_activity`),
  `feed[]` (tool calls, messages, approvals, Kanban moves; newest first), `counts`,
  `kanban` and `vault` (`configured`, `connected`, `note_count`). Live updates: the
  WebSocket event `office.update` on `/api/ws` (session_id `null`, sent to every
  client) and the SSE stream `GET /api/office/events`. Same auth as every route,
  so a paired phone can watch it. JSON-RPC: `office.snapshot`.
* `memory.obsidian_vault` (`neovarch config set memory.obsidian_vault ~/Vault`)
  turns on the vault tools and the vault section of the system prompt.
  `GET /api/memory/obsidian` reports its status.
* `appearance.accent` / `appearance.base` hold the colour chosen at first run.
  `GET/PUT /api/appearance` returns `{accent, base, on_accent}`; a change is pushed
  as the `appearance.changed` event so the phone can follow the PC.

## Data

```
~/.neovarch/
  config.yaml  .env  SOUL.md  kanban.json
  sessions/<id>.json   memory/*.md   skills/<name>/SKILL.md   logs/
```

## Development

```
uv venv .venv && uv pip install -p .venv -e '.[test]'
.venv/bin/pytest -q
python tests/mock_llm.py --port 18080   # OpenAI-compatible mock provider for manual runs
python scripts/smoke_serve.py --port 9319   # neovarch serve + mock: session.create, prompt.submit, streamed reply + one tool call
```

`neovarch --profile <name> …` keeps that profile's data in `~/.neovarch/profiles/<name>` (the desktop passes
`--profile` when one is pinned).
