#!/bin/sh
# Neovarch Agent installer (Linux x86_64 / arm64 core, Linux x86_64 desktop).
#
#   curl -fsSL https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/main/scripts/install.sh | sh
#
# Installs, all as the current user (no root):
#   * the Neovarch core (original Python agent, in core/ of
#     this repo) into ~/.neovarch/neovarch-agent, with its own Python and venv;
#   * the `neovarch` command (~/.local/bin/neovarch);
#   * the desktop app (Electron) into ~/.local/share/neovarch-agent, started
#     with `neovarch desktop` / `neovarch-desktop` or from the app menu;
#   * 9Router (https://9router.com, MIT), the default model provider: `npm i -g
#     9router` (Node.js LTS is installed into ~/.neovarch/tools/node when node >= 18
#     is missing), started in the background, with Neovarch's default model set to
#     the free OpenCode model oc/big-pickle — chat works with no API key.
#
# Neovarch never uses, reads or changes a Hermes Agent install: no `hermes`
# command, no ~/.hermes, no HERMES_HOME. Both can be installed side by side.
#
# Options (pass after `sh -s --` when piping):
#   --core-only        install only the core and the `neovarch` command
#   --no-9router       do not install/start 9Router (pick a provider later)
#   --no-extras        do not install optional extras (Obsidian) — the built-in vault graph works without them
#   --uninstall        remove Neovarch (~/.neovarch, the app, its shims)
#   --help             show help
# Desktop-bootstrap protocol (used by the desktop app on first launch):
#   --manifest | --stage <name> [--non-interactive] [--json]
#   [--dir <install dir>] [--neovarch-home <dir>] [--branch <b>] [--commit <sha>]
# Environment:
#   NEOVARCH_HOME       data home (default ~/.neovarch)
#   NEOVARCH_VERSION    desktop release tag (e.g. v1.4.8). Default: latest.
#   NEOVARCH_REF        git ref of this repo to take the core from. Default:
#                       NEOVARCH_VERSION when set, else v1.4.8.
#   NEOVARCH_CORE_SRC   local checkout of this repo (or its core/ dir) to
#                       install the core from instead of downloading.
#   NEOVARCH_KEEP_RUNNING  set (to anything) to not close a running desktop app
#                       (used by the app's own updater, which restarts itself).

set -eu

REPO="Maftuuh1922/neovrach_Agent"
RELEASES_URL="https://github.com/$REPO/releases"
ASSET="neovarch-agent-linux-x64.tar.gz"
EXE="neovarch-agent"
PY_VERSION="3.14"
# Core ref used when nothing else is asked for: the tag this installer ships with.
DEFAULT_CORE_REF="v1.4.8"

NEOVARCH_HOME="${NEOVARCH_HOME:-$HOME/.neovarch}"
CORE_DIR=""            # set after argument parsing (default $NEOVARCH_HOME/neovarch-agent)
RECEIPT_NAME=".neovarch-bootstrap-complete"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_HOME/neovarch-agent"
BIN_DIR="$HOME/.local/bin"
CLI_SHIM="$BIN_DIR/neovarch"
DESKTOP_SHIM="$BIN_DIR/neovarch-desktop"
APPS_DIR="$DATA_HOME/applications"
DESKTOP_FILE="$APPS_DIR/neovarch-agent.desktop"
ICON_DIR="$DATA_HOME/icons/hicolor/512x512/apps"
ICON_FILE="$ICON_DIR/neovarch-agent.png"

# The core installer must never be steered by a co-installed Hermes.
unset HERMES_HOME HERMES_DATA_DIR_SUFFIX HERMES_RUNTIME_DIR HERMES_INSTALL_ROOT 2>/dev/null || true

# ---------------------------------------------------------------- output ---
JSON=0
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RED=$(printf '\033[31m'); C_GRN=$(printf '\033[32m'); C_YLW=$(printf '\033[33m')
  C_BLD=$(printf '\033[1m');  C_DIM=$(printf '\033[2m');  C_RST=$(printf '\033[0m')
else
  C_RED=''; C_GRN=''; C_YLW=''; C_BLD=''; C_DIM=''; C_RST=''
fi

say()  { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$C_RED$C_BLD" "$C_RST" "$*"; }
ok()   { printf '%s ok%s %s\n' "$C_GRN" "$C_RST" "$*"; }
warn() { printf '%swarn%s %s\n' "$C_YLW" "$C_RST" "$*" >&2; }
die()  {
  printf '%serror%s %s\n' "$C_RED$C_BLD" "$C_RST" "$*" >&2
  if [ "$JSON" = 1 ] && [ -n "${CUR_STAGE:-}" ]; then
    printf '{"ok":false,"stage":"%s","reason":"%s"}\n' "$CUR_STAGE" "$(printf '%s' "$*" | tr '"\\' "''")"
  fi
  exit 1
}

banner() { printf '\n%sNeovarch Agent%s %sinstaller%s\n\n' "$C_RED$C_BLD" "$C_RST" "$C_DIM" "$C_RST"; }

usage() {
  cat <<EOF
Neovarch Agent installer

Usage:
  curl -fsSL https://raw.githubusercontent.com/$REPO/main/scripts/install.sh | sh
  curl -fsSL https://raw.githubusercontent.com/$REPO/main/scripts/install.sh | sh -s -- --core-only
  curl -fsSL https://raw.githubusercontent.com/$REPO/main/scripts/install.sh | sh -s -- --uninstall

Options:
  --core-only   Install only the Neovarch core and the \`neovarch\` command
  --no-9router  Skip 9Router (the free default model provider)
  --uninstall   Remove Neovarch Agent (only Neovarch files; Hermes is never touched)
  -h, --help    Show this help

Environment:
  NEOVARCH_HOME      data home (default ~/.neovarch)
  NEOVARCH_VERSION   desktop release tag, e.g. v1.4.8 (default: latest)
  NEOVARCH_REF       git ref for the core (default: NEOVARCH_VERSION or v1.4.8)
  NEOVARCH_CORE_SRC  install the core from a local checkout instead
EOF
}

# ------------------------------------------------------------- helpers ---
have() { command -v "$1" >/dev/null 2>&1; }

download() { # url dest
  if have curl; then
    if [ -t 2 ] && [ "$JSON" = 0 ]; then
      curl -fL --retry 3 --progress-bar -o "$2" "$1"
    else
      curl -fsSL --retry 3 -o "$2" "$1"
    fi
  elif have wget; then
    wget -q -O "$2" "$1"
  else
    die "need curl or wget to download Neovarch Agent"
  fi
}

fetch_text() { # url
  if have curl; then curl -fsSL --retry 2 "$1"; else wget -q -O - "$1"; fi
}

# Is $1 inside the Neovarch home? (refuses to operate on anything else)
inside_home() {
  case "$1" in "$NEOVARCH_HOME"|"$NEOVARCH_HOME"/*) return 0 ;; *) return 1 ;; esac
}

# A path we may create/replace/remove as "ours": never a Hermes path.
assert_not_hermes() {
  case "$1" in
    "$HOME/.hermes"|"$HOME/.hermes/"*|*/bin/hermes|*/bin/hermes-*) die "refusing to touch $1 (belongs to Hermes Agent)" ;;
  esac
}

# --------------------------------------------------------------- core ---
TOOLS_DIR=""   # $NEOVARCH_HOME/tools
UV=""

core_paths() {
  CORE_DIR="${CORE_DIR:-$NEOVARCH_HOME/neovarch-agent}"
  TOOLS_DIR="$NEOVARCH_HOME/tools"
  inside_home "$CORE_DIR" || [ -n "${NEOVARCH_ALLOW_EXTERNAL_DIR:-}" ] || die "--dir must be inside $NEOVARCH_HOME"
  assert_not_hermes "$CORE_DIR"
  # uv keeps its Python, cache and tool state under the Neovarch home.
  export UV_PYTHON_INSTALL_DIR="$TOOLS_DIR/python"
  export UV_CACHE_DIR="$NEOVARCH_HOME/cache/uv"
  export UV_TOOL_DIR="$TOOLS_DIR/uv-tools"
  export UV_NO_MODIFY_PATH=1
}

stage_uv() {
  if [ -x "$TOOLS_DIR/uv/uv" ]; then UV="$TOOLS_DIR/uv/uv"; ok "uv ($UV)"; return 0; fi
  if have uv; then
    # Use (never modify) a uv already on PATH: it is a generic tool, not Hermes.
    UV=$(command -v uv)
    case "$UV" in "$HOME/.hermes/"*) UV="" ;; esac
  fi
  if [ -z "$UV" ]; then
    step "Installing uv into $TOOLS_DIR/uv"
    mkdir -p "$TOOLS_DIR/uv"
    tmp_uv=$(mktemp)
    download "https://astral.sh/uv/install.sh" "$tmp_uv" || die "could not download the uv installer"
    env UV_INSTALL_DIR="$TOOLS_DIR/uv" UV_UNMANAGED_INSTALL="$TOOLS_DIR/uv" UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 sh "$tmp_uv" >/dev/null 2>&1 \
      || die "uv installation failed"
    rm -f "$tmp_uv"
    UV="$TOOLS_DIR/uv/uv"
  fi
  [ -x "$UV" ] || die "uv not available"
  ok "uv ($UV)"
}

resolve_commit() { # ref -> sha (best effort)
  case "$1" in
    *[!0-9a-f]*|'') ;;
    *) if [ ${#1} -ge 40 ]; then printf '%s' "$1"; return 0; fi ;;
  esac
  sha=$(fetch_text "https://api.github.com/repos/$REPO/commits/$1" 2>/dev/null | sed -n 's/^  "sha": "\([0-9a-f]\{40\}\)".*/\1/p' | head -n 1 || true)
  printf '%s' "${sha:-}"
}

stage_core() {
  mkdir -p "$NEOVARCH_HOME"
  staging="$NEOVARCH_HOME/.core-staging"
  rm -rf "$staging"; mkdir -p "$staging"
  commit=""
  # Run from a checkout of this repo (scripts/install.sh next to core/)? Then
  # install that core instead of downloading one, unless a ref was asked for.
  if [ -z "${NEOVARCH_CORE_SRC:-}" ] && [ -z "${COMMIT_ARG:-}${NEOVARCH_REF:-}" ]; then
    case "$0" in
      */install.sh)
        here=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || here=""
        if [ -n "$here" ] && [ -f "$here/../core/neovarch/cli.py" ]; then
          NEOVARCH_CORE_SRC=$(cd "$here/.." && pwd)
        fi ;;
    esac
  fi
  if [ -n "${NEOVARCH_CORE_SRC:-}" ]; then
    src="$NEOVARCH_CORE_SRC"
    [ -d "$src/core" ] && src="$src/core"
    [ -f "$src/neovarch/cli.py" ] || die "NEOVARCH_CORE_SRC has no Neovarch core: $NEOVARCH_CORE_SRC"
    step "Copying the Neovarch core from $src"
    (cd "$src" && tar --exclude=venv --exclude=__pycache__ --exclude=node_modules -cf - .) | (cd "$staging" && tar -xf -)
    commit=$(git -C "$src" rev-parse HEAD 2>/dev/null || true)
  else
    ref="${COMMIT_ARG:-${NEOVARCH_REF:-${BRANCH_ARG:-${NEOVARCH_VERSION:-$DEFAULT_CORE_REF}}}}"
    commit=$(resolve_commit "$ref")
    url="https://codeload.github.com/$REPO/tar.gz/${commit:-$ref}"
    step "Downloading the Neovarch core ($ref)"
    say "    $C_DIM$url$C_RST"
    download "$url" "$staging.tgz" || die "core download failed ($url)"
    mkdir -p "$staging.x"
    tar -xzf "$staging.tgz" -C "$staging.x" --wildcards '*/core/*' || die "archive has no core/ directory"
    top=$(find "$staging.x" -mindepth 1 -maxdepth 1 -type d | head -n 1)
    rm -rf "$staging"; mv "$top/core" "$staging"
    rm -rf "$staging.x" "$staging.tgz"
  fi
  [ -f "$staging/neovarch/cli.py" ] || die "downloaded core is incomplete"
  # Keep an existing venv across updates when the Python still matches.
  if [ -d "$CORE_DIR/venv" ]; then mv "$CORE_DIR/venv" "$staging/venv"; fi
  rm -rf "$CORE_DIR.old"
  [ -d "$CORE_DIR" ] && mv "$CORE_DIR" "$CORE_DIR.old"
  mv "$staging" "$CORE_DIR"
  rm -rf "$CORE_DIR.old"
  printf '%s\n' "${commit:-unknown}" > "$CORE_DIR/.neovarch-source-commit"
  ok "core in $CORE_DIR"
}

stage_python() {
  [ -n "$UV" ] || stage_uv
  [ -f "$CORE_DIR/pyproject.toml" ] || die "core not installed yet (run the core stage first)"
  step "Preparing Python $PY_VERSION and the core's dependencies"
  if [ ! -x "$CORE_DIR/venv/bin/python" ]; then
    "$UV" venv --quiet --python "$PY_VERSION" --python-preference only-managed "$CORE_DIR/venv" \
      || die "could not create the Python $PY_VERSION environment"
  fi
  VIRTUAL_ENV="$CORE_DIR/venv" "$UV" pip install --quiet --python "$CORE_DIR/venv/bin/python" -e "$CORE_DIR" \
    || die "dependency installation failed"
  [ -x "$CORE_DIR/venv/bin/neovarch" ] || die "the neovarch entry point was not created"
  ok "dependencies installed"
}

stage_cli() {
  [ -x "$CORE_DIR/venv/bin/neovarch" ] || die "core environment missing (run the python stage first)"
  launcher_dir="$CORE_DIR/.neovarch/bin"
  mkdir -p "$launcher_dir"
  cat > "$launcher_dir/neovarch" <<EOF
#!/bin/sh
# Neovarch Agent CLI launcher (generated by scripts/install.sh)
NEOVARCH_HOME="\${NEOVARCH_HOME:-$NEOVARCH_HOME}"
export NEOVARCH_HOME
exec "$CORE_DIR/venv/bin/neovarch" "\$@"
EOF
  chmod 755 "$launcher_dir/neovarch"
  mkdir -p "$BIN_DIR"
  assert_not_hermes "$CLI_SHIM"
  if [ -e "$CLI_SHIM" ] || [ -L "$CLI_SHIM" ]; then
    target=$(readlink "$CLI_SHIM" 2>/dev/null || true)
    case "$target" in
      "$NEOVARCH_HOME"/*|"$APP_DIR"/*|'') ;;
      *) if [ -n "$target" ]; then warn "replacing $CLI_SHIM (pointed to $target)"; fi ;;
    esac
    rm -f "$CLI_SHIM"
  fi
  ln -s "$launcher_dir/neovarch" "$CLI_SHIM"
  ok "linked $CLI_SHIM -> $launcher_dir/neovarch"

  commit=$(cat "$CORE_DIR/.neovarch-source-commit" 2>/dev/null || echo unknown)
  [ ${#commit} -ge 7 ] || commit="unknown-local"
  if [ -n "${BRANCH_ARG:-}" ]; then branch_json="\"$BRANCH_ARG\""; else branch_json=null; fi
  cat > "$CORE_DIR/$RECEIPT_NAME" <<EOF
{
  "schemaVersion": 1,
  "pinnedCommit": "$commit",
  "pinnedBranch": $branch_json,
  "completedAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "installer": "scripts/install.sh"
}
EOF
  "$CLI_SHIM" --version >/dev/null 2>&1 || die "neovarch --version failed"
  ok "$("$CLI_SHIM" --version | head -n 1)"
}

install_core() {
  core_paths
  stage_uv
  stage_core
  stage_python
  stage_cli
}

# ------------------------------------------------------------ 9Router ---
NODE_MAJOR=22          # Node.js LTS line installed when node >= 18 is missing
NODE_BIN=""; NPM_BIN=""

node_ok() { # path-to-node -> 0 when major >= 18
  v=$("$1" -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
  [ "${v:-0}" -ge 18 ] 2>/dev/null
}

stage_node() {
  if have node && node_ok "$(command -v node)" && have npm; then
    NODE_BIN=$(command -v node); NPM_BIN=$(command -v npm); ok "Node.js $(node -v)"; return 0
  fi
  if [ -x "$TOOLS_DIR/node/bin/node" ] && node_ok "$TOOLS_DIR/node/bin/node"; then
    NODE_BIN="$TOOLS_DIR/node/bin/node"; NPM_BIN="$TOOLS_DIR/node/bin/npm"
    ok "Node.js $("$NODE_BIN" -v) ($TOOLS_DIR/node)"; return 0
  fi
  case "$(uname -m 2>/dev/null)" in
    x86_64|amd64) narch=x64 ;; aarch64|arm64) narch=arm64 ;;
    *) warn "no Node.js build for $(uname -m); install Node.js 18+ and run: npm install -g 9router"; return 1 ;;
  esac
  step "Installing Node.js $NODE_MAJOR LTS into $TOOLS_DIR/node (needed by 9Router)"
  base="https://nodejs.org/dist/latest-v$NODE_MAJOR.x"
  sums=$(fetch_text "$base/SHASUMS256.txt") || { warn "could not reach nodejs.org"; return 1; }
  file=$(printf '%s\n' "$sums" | awk '{print $2}' | grep -E "^node-v[0-9.]+-linux-$narch\.tar\.gz$" | head -n 1)
  [ -n "$file" ] || { warn "Node.js archive for linux-$narch not found"; return 1; }
  want=$(printf '%s\n' "$sums" | awk -v f="$file" '$2==f {print $1}')
  tmpn=$(mktemp -d)
  download "$base/$file" "$tmpn/$file" || { rm -rf "$tmpn"; warn "Node.js download failed"; return 1; }
  if have sha256sum; then
    got=$(sha256sum "$tmpn/$file" | awk '{print $1}')
    [ "$got" = "$want" ] || { rm -rf "$tmpn"; warn "Node.js checksum mismatch"; return 1; }
  fi
  tar -xzf "$tmpn/$file" -C "$tmpn" || { rm -rf "$tmpn"; warn "could not unpack Node.js"; return 1; }
  rm -rf "$TOOLS_DIR/node"; mkdir -p "$TOOLS_DIR"
  mv "$tmpn/${file%.tar.gz}" "$TOOLS_DIR/node"; rm -rf "$tmpn"
  NODE_BIN="$TOOLS_DIR/node/bin/node"; NPM_BIN="$TOOLS_DIR/node/bin/npm"
  ok "Node.js $("$NODE_BIN" -v)"
}

stage_9router() {
  core_paths
  if [ -n "${NEOVARCH_NO_9ROUTER:-}" ]; then say "    9Router skipped (NEOVARCH_NO_9ROUTER)"; return 0; fi
  if have 9router || [ -x "$TOOLS_DIR/npm/bin/9router" ]; then
    ok "9Router already installed"
  else
    stage_node || { warn "9Router not installed. Later: npm install -g 9router"; return 0; }
    step "Installing 9Router (npm install -g 9router)"
    PATH="$(dirname "$NODE_BIN"):$PATH"; export PATH
    gprefix=$("$NPM_BIN" prefix -g 2>/dev/null || echo "")
    if [ -n "$gprefix" ] && [ -w "$gprefix" ] && { [ ! -d "$gprefix/lib" ] || [ -w "$gprefix/lib" ]; }; then
      "$NPM_BIN" install -g 9router --no-fund --no-audit >/dev/null 2>&1 || { warn "npm install -g 9router failed"; return 0; }
    else
      # The system npm needs root for -g: install for this user only, under the Neovarch home.
      "$NPM_BIN" install -g --prefix "$TOOLS_DIR/npm" 9router --no-fund --no-audit >/dev/null 2>&1 \
        || { warn "npm install 9router failed"; return 0; }
      mkdir -p "$BIN_DIR"; ln -sf "$TOOLS_DIR/npm/bin/9router" "$BIN_DIR/9router"
    fi
    ok "9Router installed"
  fi
  [ -x "$CLI_SHIM" ] || { warn "neovarch command missing; skipping 9Router setup"; return 0; }
  step "Starting 9Router and choosing the free default model"
  if PATH="$TOOLS_DIR/node/bin:$TOOLS_DIR/npm/bin:$PATH" "$CLI_SHIM" router setup; then
    ok "9Router ready (dashboard: http://localhost:20128/dashboard)"
  else
    warn "9Router needs one step in its dashboard: open http://localhost:20128/dashboard"
    say "      (the desktop app shows a \"Buka dashboard 9Router\" button for it)"
  fi
}

# ---------------------------------------------------- desktop protocol ---
manifest() {
  cat <<'EOF'
{"protocol_version":1,"stages":[{"name":"uv","title":"Alat Python (uv)","category":"tooling","needs_user_input":false},{"name":"core","title":"Inti Neovarch","category":"source","needs_user_input":false},{"name":"python","title":"Lingkungan Python","category":"dependencies","needs_user_input":false},{"name":"cli","title":"Perintah neovarch","category":"launcher","needs_user_input":false},{"name":"9router","title":"9Router (model gratis)","category":"provider","needs_user_input":false}]}
EOF
}

run_stage() { # name
  CUR_STAGE="$1"
  core_paths
  case "$1" in
    uv) stage_uv ;;
    core) stage_core ;;
    python) stage_uv; stage_python ;;
    cli) stage_cli ;;
    9router) stage_9router ;;
    *) die "unknown stage: $1" ;;
  esac
  [ "$JSON" = 1 ] && printf '{"ok":true,"stage":"%s"}\n' "$1"
  return 0
}

# ------------------------------------------------------------ desktop ---
has_lib() { # soname
  if have ldconfig && ldconfig -p 2>/dev/null | grep -q "$1"; then return 0; fi
  for d in /usr/lib /usr/lib64 /usr/lib/x86_64-linux-gnu /lib/x86_64-linux-gnu /usr/local/lib; do
    [ -e "$d/$1" ] && return 0
  done
  return 1
}

refresh_menu() { if have update-desktop-database; then update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true; fi; }

check_deps() {
  missing=''
  has_lib libgtk-3.so.0 || missing="$missing gtk3"
  has_lib libnss3.so || missing="$missing nss"
  has_lib libasound.so.2 || missing="$missing alsa"
  has_lib libsecret-1.so.0 || missing="$missing libsecret"
  [ -z "$missing" ] && { ok "runtime libraries found (GTK 3, NSS, ALSA, libsecret)"; return 0; }
  warn "missing runtime libraries:$missing"
  if have apt-get; then say "      install with: sudo apt-get install -y libgtk-3-0 libnss3 libasound2 libsecret-1-0"
  elif have dnf; then say "      install with: sudo dnf install -y gtk3 nss alsa-lib libsecret"
  elif have pacman; then say "      install with: sudo pacman -S --needed gtk3 nss alsa-lib libsecret"
  else say "      install GTK 3, NSS, ALSA and libsecret with your package manager"; fi
}

sandbox_ok() { # app dir
  sb="$1/chrome-sandbox"
  [ -e "$sb" ] || return 0
  if [ -u "$sb" ] && [ "$(stat -c %u "$sb" 2>/dev/null)" = "0" ]; then return 0; fi
  if have unshare && unshare --user --map-root-user true >/dev/null 2>&1; then return 0; fi
  return 1
}

write_desktop_entry() { # icon exec_flags
  cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Neovarch Agent
Comment=Neovarch Agent desktop
Exec="$APP_DIR/$EXE"$2 %U
Icon=$1
Path=$APP_DIR
Terminal=false
Categories=Development;Utility;
MimeType=x-scheme-handler/neovarch;
StartupWMClass=Neovarch Agent
EOF
  chmod 644 "$DESKTOP_FILE"
}

install_desktop() {
  version="${NEOVARCH_VERSION:-}"
  if [ -n "$version" ]; then
    case "$version" in v*) ;; *) version="v$version" ;; esac
    url="$RELEASES_URL/download/$version/$ASSET"; label="$version"
  else
    url="$RELEASES_URL/latest/download/$ASSET"; label="latest"
  fi
  have tar || die "need tar to unpack Neovarch Agent"
  tmp=$(mktemp -d 2>/dev/null || mktemp -d -t neovarch)
  trap 'rm -rf "$tmp"' EXIT INT TERM

  step "Downloading the Neovarch desktop app ($label)"
  say "    $C_DIM$url$C_RST"
  download "$url" "$tmp/$ASSET" || die "download failed. Check the tag or see $RELEASES_URL"
  mkdir -p "$tmp/x"
  tar -xzf "$tmp/$ASSET" -C "$tmp/x" || die "could not unpack $ASSET"
  src=$(find "$tmp/x" -maxdepth 3 -type f -name "$EXE" 2>/dev/null | head -n 1)
  [ -n "$src" ] || die "archive layout unexpected (no $EXE executable)"
  src=$(dirname "$src"); chmod 755 "$src/$EXE"

  # Close a running Neovarch desktop (only ours: matched by its install path).
  # The desktop's own "Update sekarang" sets NEOVARCH_KEEP_RUNNING=1: it shows
  # this log and asks the user to restart when the install finishes.
  if [ -z "${NEOVARCH_KEEP_RUNNING:-}" ] && have pkill; then pkill -f "$APP_DIR/$EXE" >/dev/null 2>&1 || true; fi

  mkdir -p "$DATA_HOME" "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"
  rm -rf "$APP_DIR"; mv "$src" "$APP_DIR"
  ok "desktop app in $APP_DIR"
  rm -f "$DESKTOP_SHIM"; ln -s "$APP_DIR/$EXE" "$DESKTOP_SHIM"
  ok "linked $DESKTOP_SHIM -> $APP_DIR/$EXE"

  icon="neovarch-agent"
  if [ -f "$APP_DIR/resources/app.asar.unpacked/dist/apple-touch-icon.png" ]; then
    cp "$APP_DIR/resources/app.asar.unpacked/dist/apple-touch-icon.png" "$ICON_FILE"
  elif ! download "https://raw.githubusercontent.com/$REPO/main/assets/brand/app_icon.png" "$ICON_FILE" >/dev/null 2>&1; then
    icon="utilities-terminal"
  fi
  exec_flags=''
  if ! sandbox_ok "$APP_DIR"; then
    exec_flags=' --no-sandbox'
    warn "the Chromium sandbox is unavailable here; the menu entry starts the app with --no-sandbox"
    say "      to keep the sandbox (needs sudo once):"
    say "        sudo chown root:root '$APP_DIR/chrome-sandbox' && sudo chmod 4755 '$APP_DIR/chrome-sandbox'"
  fi
  write_desktop_entry "$icon" "$exec_flags"
  refresh_menu
  ok "added menu entry $DESKTOP_FILE"
  check_deps
}

# ----------------------------------------------------------- uninstall ---
uninstall() {
  banner
  step "Removing Neovarch Agent"
  removed=0
  for shim in "$CLI_SHIM" "$DESKTOP_SHIM"; do
    if [ -L "$shim" ] || [ -e "$shim" ]; then
      assert_not_hermes "$shim"; rm -f "$shim"; ok "removed $shim"; removed=1
    fi
  done
  if have pkill; then pkill -f "$APP_DIR/$EXE" >/dev/null 2>&1 || true; fi
  # 9Router installed by us under the Neovarch home goes with it (a global npm one stays).
  r9="$BIN_DIR/9router"
  if [ -L "$r9" ]; then
    case "$(readlink "$r9")" in "$NEOVARCH_HOME"/*) rm -f "$r9"; ok "removed $r9"
      if have pkill; then pkill -f "$NEOVARCH_HOME/tools/npm" >/dev/null 2>&1 || true; fi ;; esac
  fi
  [ -e "$DESKTOP_FILE" ] && { rm -f "$DESKTOP_FILE"; ok "removed $DESKTOP_FILE"; removed=1; }
  rm -f "$ICON_FILE"
  [ -d "$APP_DIR" ] && { rm -rf "$APP_DIR"; ok "removed $APP_DIR"; removed=1; }
  if [ -d "$NEOVARCH_HOME" ]; then
    assert_not_hermes "$NEOVARCH_HOME"
    case "$NEOVARCH_HOME" in "$HOME"|"/"|"") die "refusing to remove $NEOVARCH_HOME" ;; esac
    rm -rf "$NEOVARCH_HOME"; ok "removed $NEOVARCH_HOME"; removed=1
  fi
  refresh_menu
  if [ "$removed" -eq 0 ]; then say "Neovarch Agent is not installed."
  else say ""; say "Neovarch Agent uninstalled. A Hermes Agent install, if any, was not touched."; fi
}

# -------------------------------------------------------------- extras ---
# Optional extras (Obsidian for the vault): official AppImage from obsidian.md's GitHub
# releases into ~/.local, skipped when already installed. Never bundled with Neovarch.
install_extras() {
  case "${NEOVARCH_EXTRAS_AUTO:-1}" in 0|false|no|off) say "  extras skipped (--no-extras)"; return 0 ;; esac
  [ -x "$CLI_SHIM" ] || return 0
  say "  checking optional extras (Obsidian)…"
  if "$CLI_SHIM" extras ensure --reason install; then :; else
    warn "optional extras were not installed (the app works without them; retry: neovarch extras ensure)"
  fi
}

# ---------------------------------------------------------------- main ---
main() {
  action=install; core_only=0; STAGE=''; BRANCH_ARG=''; COMMIT_ARG=''
  while [ $# -gt 0 ]; do
    case "$1" in
      --uninstall) action=uninstall ;;
      --core-only|--no-desktop) core_only=1 ;;
      --no-9router) NEOVARCH_NO_9ROUTER=1 ;;
      --no-extras) NEOVARCH_EXTRAS_AUTO=0 ;;
      --manifest) action=manifest ;;
      --stage) action=stage; STAGE="${2:-}"; shift ;;
      --non-interactive) ;;
      --json) JSON=1 ;;
      --dir) CORE_DIR="${2:-}"; shift ;;
      --neovarch-home) NEOVARCH_HOME="${2:-}"; shift ;;
      --branch) BRANCH_ARG="${2:-}"; shift ;;
      --commit) COMMIT_ARG="${2:-}"; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown option: $1 (try --help)" ;;
    esac
    shift
  done
  NEOVARCH_HOME="${NEOVARCH_HOME%/}"
  assert_not_hermes "$NEOVARCH_HOME"

  case "$action" in
    uninstall) uninstall; exit 0 ;;
    manifest) manifest; exit 0 ;;
    stage) run_stage "$STAGE"; exit 0 ;;
  esac

  os=$(uname -s 2>/dev/null || echo unknown)
  arch="${NEOVARCH_FORCE_ARCH:-$(uname -m 2>/dev/null || echo unknown)}"
  case "$os" in
    Linux) ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
      banner; say "On Windows, run this in PowerShell instead:"
      say "  irm https://raw.githubusercontent.com/$REPO/main/scripts/install.ps1 | iex"; exit 1 ;;
    Darwin) banner; say "macOS builds are not available yet: $RELEASES_URL/latest"; exit 1 ;;
    *) banner; say "Neovarch Agent for $os is not available yet."; exit 1 ;;
  esac

  banner
  install_core
  stage_9router
  install_extras
  if [ "$core_only" = 0 ]; then
    case "$arch" in
      x86_64|amd64) install_desktop ;;
      *) warn "the desktop app is available for Linux x86_64 only; installed the core and CLI" ;;
    esac
  fi

  case ":${PATH:-}:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not in your PATH"
       say "      add this to your shell profile (~/.bashrc, ~/.zshrc):"
       say "        export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
  esac
  say ""
  say "${C_BLD}Neovarch Agent is installed.${C_RST} Data: $NEOVARCH_HOME"
  say "  ${C_RED}${C_BLD}neovarch${C_RST}            chat in the terminal (free model via 9Router)"
  say "  ${C_RED}${C_BLD}neovarch router${C_RST}     9Router status (dashboard: http://localhost:20128/dashboard)"
  [ "$core_only" = 0 ] && say "  ${C_RED}${C_BLD}neovarch desktop${C_RST}    open the desktop app"
  say "Uninstall: curl -fsSL https://raw.githubusercontent.com/$REPO/main/scripts/install.sh | sh -s -- --uninstall"
}

main "$@"
