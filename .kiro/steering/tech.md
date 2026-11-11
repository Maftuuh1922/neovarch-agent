# Neovarch Agent — Tech

## Layout (repo root)

- `core/` — Neovarch core (Python). The agent runtime: chat loop, tools, sessions, skills, memory, Kanban.
- `desktop/` — Electron desktop app that hosts the core.
- `android/`, `ios/`, `lib/` — Flutter phone remote app (Dart).
- `relay/` — token-locked gateway for phone remote access.
- `landing/` — marketing site. Docs live at https://maftuuh1922.github.io/neorachAgent_lp/docs/
- `scripts/` — install scripts (`install.sh`, `install.ps1`).
- `docs/` — guides and the remote protocol.

## Stack

- Core: Python (aiohttp, PyYAML). Entry point: the `neovarch` command.
- Desktop: Electron (TypeScript).
- Phone remote: Flutter/Dart.
- Config: `~/.neovarch/config.yaml`, secrets in `~/.neovarch/.env`.
- No Neovarch server: everything runs on the user’s own PC.

## Conventions

- Keep secrets out of the repo: API keys only in `~/.neovarch/.env`.
- Risky commands must go through the approval flow (`ask` / `off`); never bypass approvals.
- Changes go on a feature branch; never commit directly to the default branch.
