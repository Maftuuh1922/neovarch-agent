<p align="center">
  <img src="docs/assets/logo.png" alt="Neovarch Agent logo" width="160" height="160">
</p>

<h1 align="center">Neovarch Agent</h1>

<p align="center">
  <a href="https://maftuuh1922.github.io/neorachAgent_lp/">Website</a> ·
  <a href="https://maftuuh1922.github.io/neorachAgent_lp/docs/">Docs</a> ·
  <a href="https://github.com/Maftuuh1922/neovrach_Agent/releases/latest">Download</a> ·
  <a href="docs/remote-protocol.md">Remote protocol</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

<p align="center">
  <a href="https://maftuuh1922.github.io/neorachAgent_lp/docs/"><img src="https://img.shields.io/badge/docs-website-C8101A" alt="Docs"></a>
  <a href="https://github.com/Maftuuh1922/neovrach_Agent/releases/latest"><img src="https://img.shields.io/github/v/release/Maftuuh1922/neovrach_Agent?label=release&color=C8101A" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-informational" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20Android-0A0A0A" alt="Platform">
</p>

**An AI agent by NeovarchLabs that runs on your own PC (Windows, Linux) and that you can control from your Android phone.
The desktop is the core: chat with tools, sessions, skills, memory, and a Kanban board, with all data kept in `~/.neovarch`.
The phone is just a remote: pair it with a QR code and drive the agent on your PC.**

Use any model that speaks the OpenAI `/chat/completions` API: OpenAI, OpenRouter, Groq, DeepSeek, Ollama,
or a custom endpoint (including a local server). Pick a provider with `neovarch setup`; API keys are stored in
`~/.neovarch/.env` (`%LOCALAPPDATA%\neovarch\.env` on Windows).

<table>
  <tr>
    <td><b>Core on your own PC</b></td>
    <td>The Electron desktop app runs the Neovarch core (Python, the <code>neovarch</code> command); your data stays on your machine.</td>
  </tr>
  <tr>
    <td><b>Phone remote</b></td>
    <td>Pair your phone by QR, then chat, approve commands, and watch tasks and PC status over LAN or Tailscale.</td>
  </tr>
  <tr>
    <td><b>Chat with tools</b></td>
    <td>Streaming chat with the <code>shell</code>, <code>read_file</code>, <code>write_file</code>, <code>edit_file</code>, <code>web_fetch</code>, <code>memory</code>, and <code>skill</code> tools.</td>
  </tr>
  <tr>
    <td><b>Command approvals</b></td>
    <td>Risky commands wait for your OK (<code>ask</code> / <code>off</code> modes), including from an Android notification.</td>
  </tr>
  <tr>
    <td><b>Sessions, skills, memory, Kanban</b></td>
    <td>Saved chats you can resume, local skills, note-based memory, and a Kanban board for tasks.</td>
  </tr>
  <tr>
    <td><b>Token-locked gateway</b></td>
    <td>Remote access goes through a separate token-locked gateway; generate a new token to revoke every paired phone.</td>
  </tr>
</table>

---

## Quick Install

**Linux (x86_64):**

```bash
curl -fsSL https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/main/scripts/install.sh | sh
```

**Windows (x64), PowerShell:**

```powershell
irm https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/main/scripts/install.ps1 | iex
```

**Android:** download `neovarch-agent-android-arm64.apk` (most modern phones) or
`neovarch-agent-android-universal.apk` from [Releases](https://github.com/Maftuuh1922/neovrach_Agent/releases/latest).

The Windows `.exe` installer, Linux AppImage/`.deb`, and the npm launcher are on Releases too. macOS and Linux ARM64 are not available yet.

---

## Getting Started

```bash
neovarch setup              # pick a model provider and save your API key
neovarch                    # chat in the terminal
neovarch -q "hello"         # run a single prompt and exit
neovarch --resume <id>      # resume a session
neovarch sessions           # list, view, or delete saved chats
neovarch config show        # view or edit config.yaml
neovarch desktop            # open the desktop app
neovarch update             # how to update Neovarch
neovarch version            # print the version
```

Pair your phone: on the PC open **Pengaturan ▸ Remote / Perangkat ▸ Aktifkan akses remote** (Settings ▸ Remote / Devices ▸ Enable remote access), then on the phone choose
**Pindai QR dari PC** (Scan QR from PC).

Full guide (model setup, phone pairing, building from source): <https://maftuuh1922.github.io/neorachAgent_lp/docs/>

---

## Documentation

A plain-language guide. No coding knowledge needed.

### What is Neovarch Agent?

<table>
<tr><td><b>What it is</b></td><td>An AI helper that lives on your own computer. You type what you want in normal words and it does the work on your PC: runs commands, reads and writes files, fetches web pages.</td></tr>
<tr><td><b>Your PC is the brain</b></td><td>The agent, your chats and your settings all stay on your computer. There is no Neovarch server.</td></tr>
<tr><td><b>Your phone is a remote</b></td><td>The Android app connects to your PC so you can chat, approve actions and check tasks. Your PC must be on.</td></tr>
<tr><td><b>What leaves your PC</b></td><td>Only the conversation sent to the AI model you choose.</td></tr>
</table>

### What you need

| Item | Details |
|---|---|
| **PC** | Windows 64-bit (x64) or Linux 64-bit (x86_64). macOS and Linux ARM64 are not available yet. |
| **Internet** | To download the app and talk to an online AI model. |
| **API key** | From a model provider (see Step 2), *or* a free local model with Ollama. |
| **Android phone** | Optional, to use as a remote. |

You don't need Python or anything else first. The installer brings everything it needs.

| Word | Meaning |
|---|---|
| **Terminal** / **PowerShell** | A window where you type commands instead of clicking buttons (PowerShell on Windows). |
| **Command** | One line of text you paste into the terminal and run with **Enter**. |
| **Provider** | The company or program that runs the AI model, e.g. OpenAI or OpenRouter. |
| **API key** | A long secret password that lets Neovarch use your account at that provider. |

### Step 1: Install on your PC

| | Windows | Linux |
|---|---|---|
| **1. Open** | Start → type `PowerShell` → **Windows PowerShell** (no admin needed) | Search **Terminal** in the app menu |
| **2. Paste & Enter** | `irm https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/main/scripts/install.ps1 \| iex` | `curl -fsSL https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/main/scripts/install.sh \| sh` |
| **3. Wait for** | **Neovarch Agent is installed.** | **Neovarch Agent is installed.** |
| **4. Then** | Close and open a **new** PowerShell | Open a **new** terminal |
| **If warned** | SmartScreen "Windows protected your PC": **More info → Run anyway** (app isn't code-signed yet) | Missing libraries (GTK 3, NSS, ALSA, libsecret): run the `apt` / `dnf` / `pacman` command it prints |

Prefer a normal installer? Download from [Releases](https://github.com/Maftuuh1922/neovrach_Agent/releases/latest):

| Your PC | File |
|---|---|
| Windows | `neovarch-agent-windows-x64-setup.exe` (installer) or `neovarch-agent-windows-x64.zip` (portable) |
| Linux | `neovarch-agent-linux-x64.AppImage` (make executable, then run), `.deb` (Debian/Ubuntu), or `.tar.gz` |

The first time you open the app, it installs the Neovarch core by itself if it's missing.

### Step 2: Get an API key

| Provider | Key needed? | Notes |
|---|---|---|
| **OpenAI** | Yes | Create a key on the provider's website. |
| **OpenRouter** | Yes | Many models behind one key. |
| **Groq** | Yes | |
| **DeepSeek** | Yes | |
| **Ollama** | **No, free** | Runs a model on your own PC at `http://127.0.0.1:11434/v1`. A powerful PC helps. |
| **custom** | Usually | Any service that speaks the OpenAI chat API; you give its Base URL (ends in `/v1`). |

| Question | Answer |
|---|---|
| **Where is my key stored?** | In `.env`: `~/.neovarch/.env` on Linux, `%LOCALAPPDATA%\neovarch\.env` on Windows. Not in `config.yaml`. |
| **Keep it secret?** | Yes. Anyone with your key can use your account and spend your money. If it leaks, delete it on the provider's site and make a new one. |

### Step 3: Run setup and start your first chat

| Step | What to do |
|---|---|
| 1 | In a new terminal, run `neovarch setup` |
| 2 | Type the number of your provider, press **Enter** |
| 3 | Press **Enter** for the suggested model, or type another name (for **custom** it also asks for the Base URL) |
| 4 | Paste your API key, press **Enter** (nothing shows while you paste, that's normal) |
| 5 | You see `saved … (provider …, model …)`. Done. |

| Way to chat | How |
|---|---|
| **Desktop app (easiest)** | Open **Neovarch Agent** from the Start/app menu, or run `neovarch desktop`. Click **Sesi baru** (New session). |
| **Terminal** | Run `neovarch` and type after `›`. `/new` = fresh chat, `/exit` = quit. |

Try: *"Make a folder called test-neovarch, write a file notes.md with 3 project ideas, then show it."* Every chat is saved.

### Step 4: Connect your phone (optional)

| Step | What to do |
|---|---|
| **1. Download** | From [Releases](https://github.com/Maftuuh1922/neovrach_Agent/releases/latest) get `neovarch-agent-android-arm64.apk` (most phones) or `neovarch-agent-android-universal.apk` |
| **2. Install** | Open the file, allow **install unknown apps**, tap **Install** (it's signed with a test key, so Android may warn) |
| **3. Same network** | Phone and PC on the same Wi-Fi. Away from home: [Tailscale](https://tailscale.com) on both, use the PC's `100.x` address |
| **4. On the PC** | **Pengaturan ▸ Remote / Perangkat** (Settings ▸ Remote / Devices) → turn on **Aktifkan akses remote** (Enable remote access) |
| **5. On the phone** | **Pindai QR dari PC** (Scan QR from PC), or **Masukkan alamat & token** (e.g. `192.168.1.5:9319` + token) → **Hubungkan** (Connect) |

| Phone tab | What it does |
|---|---|
| **Chat** | Talk to the agent on your PC |
| **Tugas** | Tasks (Kanban board) |
| **Setujui** | Approve risky commands |
| **PC** | Status, switch or forget the PC |

**Lost your phone?** On the PC press **Buat token baru** (Create new token): every paired phone is disconnected. Treat the QR code like a password.

### Approving commands

Risky commands (deleting with `rm -rf`, `sudo`, formatting disks, shutting down, git force-push, running a script straight from the internet) **wait for your OK**. Normal commands run right away.

| Choice | What happens |
|---|---|
| **Once** | Run this command one time |
| **This session** | Allow this exact command for the rest of this chat |
| **Deny** | Don't run it; the agent is told you said no |

| Where | How it asks |
|---|---|
| Desktop app | Inside the chat |
| Phone | **Setujui** tab + Android notification (answering on one device closes it on the other) |
| Terminal | `Allow? [o]nce / [s]ession / [N]o` (Enter alone = no) |
| No answer in **5 minutes** | Denied |

| Setting | Command |
|---|---|
| Ask first (default, recommended) | `neovarch config set approvals.mode ask` |
| Never ask (test machines only) | `neovarch config set approvals.mode off` |

### Updating and uninstalling

| Action | Linux | Windows (PowerShell) |
|---|---|---|
| **Update** (keeps chats & settings) | Re-run the install command | Re-run the install command |
| **Uninstall** (removes app, command, chats & keys) | `curl -fsSL https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/main/scripts/install.sh \| sh -s -- --uninstall` | `& ([scriptblock]::Create((irm https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/main/scripts/install.ps1))) -Uninstall` |
| **Phone** | Uninstall like any Android app | |

`neovarch update` prints the update commands for you.

### FAQ and troubleshooting

| Problem | Fix |
|---|---|
| `neovarch` not recognized / command not found | Open a **new** terminal. On Linux, if it still fails, add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc` (or `~/.zshrc`). |
| "Windows protected your PC" | Builds aren't code-signed yet: **More info → Run anyway**. |
| No answer, or **HTTP 401** | API key wrong, expired or missing. Run `neovarch setup` and paste a fresh key. |
| **HTTP 404** from provider | Usually a wrong model name or Base URL. Re-run `neovarch setup`; check with `neovarch config show`. |
| "Add model" in desktop app doesn't work | Known issue in v1.3.0. Use `neovarch setup` instead. |
| Phone can't connect | Same Wi-Fi (or both on Tailscale) · desktop app open with **Aktifkan akses remote** on · allow port **9319** in the PC firewall (never open it to the internet) · use the PC's home address (often `192.168.x.x`) · token renewed? scan the new QR. |
| Android won't install the APK | Allow "install unknown apps" for your browser/file manager. If an older APK won't update, uninstall it first. |
| Linux desktop app won't open | Install GTK 3, NSS, ALSA, libsecret. For the AppImage, `chmod +x` the file first. |

Still stuck? Open an [issue on GitHub](https://github.com/Maftuuh1922/neovrach_Agent/issues). Full docs (Indonesian): <https://maftuuh1922.github.io/neorachAgent_lp/docs/>

---

## Acknowledgements

Inspired by [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research.

PowerPoint decks are made with [PPT Master](https://github.com/hugohe3/ppt-master) by Hugo He (MIT), downloaded on demand. See [`docs/ppt.md`](docs/ppt.md).

---

## License

MIT, © 2026 Maftuuh1922 / NeovarchLabs. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
