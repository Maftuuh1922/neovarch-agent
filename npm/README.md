# neovarch-agent (npm)

Installs the **Neovarch Agent** desktop app and the Neovarch core (into `~/.neovarch`), and adds a `neovarch` command.

```bash
npm i -g https://github.com/Maftuuh1922/neovrach_Agent/releases/latest/download/neovarch-agent-npm.tgz
neovarch
```

Once the package is published to the npm registry, `npm i -g neovarch-agent` works too.

- Supported: Linux x86_64 (needs GTK 3, NSS, ALSA and libsecret), Windows x64. macOS and Linux ARM64 print a "not available yet" message.
- It installs the portable desktop build (Electron): `neovarch-agent-linux-x64.tar.gz` or `neovarch-agent-windows-x64.zip`. On Linux it adds `--no-sandbox` automatically when the Chromium sandbox is unavailable.
- The Neovarch core (the original Python agent in this repo's `core/`; it contains no Hermes Agent code) is installed into `~/.neovarch/neovarch-agent` (`%LOCALAPPDATA%\neovarch` on Windows) by `scripts/install.sh --core-only` / `install.ps1 -CoreOnly`. `neovarch` with no arguments opens the app; `neovarch <command>` runs the core CLI.
- A Hermes Agent install (`hermes`, `~/.hermes`) is never used or changed; both can be installed side by side.
- The app is downloaded from the matching GitHub release into `~/.neovarch/app` during install, or on first run.
- `neovarch --update` re-downloads the app and updates the core, `neovarch --uninstall` removes `~/.neovarch` (and only that), `npm uninstall -g neovarch-agent` removes the command.
- `NEOVARCH_VERSION=v1.4.8` pins a release tag. `NEOVARCH_SKIP_DOWNLOAD=1` skips the download during `npm install`.

Node.js 18 or newer. No dependencies.
