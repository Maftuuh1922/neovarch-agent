# Neovarch Agent — Product

Neovarch Agent is an AI agent by NeovarchLabs that runs on the user’s own PC (Windows, Linux) and is controlled from an Android phone.

## How it works

- The desktop is the core: the Electron desktop app runs the Neovarch core (Python, the `neovarch` command). Chat with tools, sessions, skills, memory, and a Kanban board. All data stays in `~/.neovarch`.
- The phone is only a remote: pair it with a QR code, then chat, approve commands, and watch tasks and PC status over LAN or Tailscale.
- There is no Neovarch server. The only thing that leaves the PC is the conversation sent to the AI model the user chooses.

## Capabilities

- Streaming chat with tools: `shell`, `read_file`, `write_file`, `edit_file`, `web_fetch`, `memory`, `skill`.
- Command approvals: risky commands wait for the user’s OK (`ask` / `off` modes), including from an Android notification.
- Sessions, local skills, note-based memory, Kanban board for tasks.
- Remote access goes through a separate token-locked gateway; generating a new token revokes every paired phone.

## Models

Any model that speaks the OpenAI `/chat/completions` API: OpenAI, OpenRouter, Groq, DeepSeek, Ollama, or a custom endpoint (including a local server). Pick a provider with `neovarch setup`; API keys live in `~/.neovarch/.env` (`%LOCALAPPDATA%\neovarch\.env` on Windows).
