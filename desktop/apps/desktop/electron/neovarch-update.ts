/**
 * Neovarch's own "Check for Updates…": reads GitHub Releases of the Neovarch
 * repo instead of the upstream feed-based updater (feed-config, App Installer,
 * MSIX, mac). Linux installs made by scripts/install.sh re-run that installer
 * for the new tag; AppImage/deb (and anything unknown) get the release page;
 * Windows downloads the NSIS setup from the release assets and launches it.
 *
 * Everything with a decision in it is a pure function exported for tests;
 * createNeovarchUpdater() wires those to the network, the filesystem and the
 * process table through injected deps.
 */
import fs from 'node:fs'
import path from 'node:path'

export const NEOVARCH_REPO = 'Maftuuh1922/neovrach_Agent'
export const LATEST_RELEASE_API = `https://api.github.com/repos/${NEOVARCH_REPO}/releases/latest`
export const RELEASES_PAGE = `https://github.com/${NEOVARCH_REPO}/releases`
export const INSTALL_SH_URL = `https://raw.githubusercontent.com/${NEOVARCH_REPO}/main/scripts/install.sh`
export const WINDOWS_SETUP_ASSET = 'neovarch-agent-windows-x64-setup.exe'
/** The quiet startup check runs at most once per this window. */
export const STARTUP_CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000
const FETCH_TIMEOUT_MS = 10_000
const MAX_LOG_LINES = 400

// ---------------------------------------------------------------- semver ---

export interface Semver {
  major: number
  minor: number
  patch: number
  pre: string[]
}

const SEMVER_RE = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/

export function parseSemver(input: unknown): Semver | null {
  if (typeof input !== 'string') {
    return null
  }

  const match = SEMVER_RE.exec(input.trim())

  if (!match) {
    return null
  }

  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
    pre: match[4] ? match[4].split('.') : []
  }
}

function comparePre(a: string[], b: string[]): number {
  // A release outranks any prerelease of the same core version.
  if (!a.length || !b.length) {
    return a.length === b.length ? 0 : a.length ? -1 : 1
  }

  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    if (a[i] === undefined) {
      return -1
    }

    if (b[i] === undefined) {
      return 1
    }

    const an = /^\d+$/.test(a[i]) ? Number(a[i]) : null
    const bn = /^\d+$/.test(b[i]) ? Number(b[i]) : null

    if (an !== null && bn !== null) {
      if (an !== bn) {
        return an < bn ? -1 : 1
      }
    } else if (an !== null || bn !== null) {
      return an !== null ? -1 : 1
    } else if (a[i] !== b[i]) {
      return a[i] < b[i] ? -1 : 1
    }
  }

  return 0
}

/** <0 when a<b, 0 when equal, >0 when a>b. Throws on unparseable input. */
export function compareSemver(a: string, b: string): number {
  const pa = parseSemver(a)
  const pb = parseSemver(b)

  if (!pa || !pb) {
    throw new Error(`not a semantic version: ${!pa ? a : b}`)
  }

  for (const key of ['major', 'minor', 'patch'] as const) {
    if (pa[key] !== pb[key]) {
      return pa[key] < pb[key] ? -1 : 1
    }
  }

  return comparePre(pa.pre, pb.pre)
}

/** True only when both parse and the release tag is strictly newer. */
export function isNewerRelease(tag: string | null | undefined, current: string | null | undefined): boolean {
  if (!parseSemver(tag) || !parseSemver(current)) {
    return false
  }

  return compareSemver(tag as string, current as string) > 0
}

// --------------------------------------------------------------- release ---

export interface ReleaseAsset {
  name: string
  url: string
  size: number
}

export interface LatestRelease {
  tag: string
  name: string
  htmlUrl: string
  body: string
  publishedAt: string | null
  assets: ReleaseAsset[]
}

export function parseLatestRelease(json: unknown): LatestRelease | null {
  if (!json || typeof json !== 'object') {
    return null
  }

  const raw = json as Record<string, unknown>
  const tag = typeof raw.tag_name === 'string' ? raw.tag_name.trim() : ''

  if (!parseSemver(tag) || raw.draft === true) {
    return null
  }

  const assets = Array.isArray(raw.assets) ? raw.assets : []

  return {
    tag,
    name: typeof raw.name === 'string' && raw.name.trim() ? raw.name.trim() : tag,
    htmlUrl:
      typeof raw.html_url === 'string' && raw.html_url.startsWith('https://github.com/')
        ? raw.html_url
        : `${RELEASES_PAGE}/tag/${encodeURIComponent(tag)}`,
    body: typeof raw.body === 'string' ? raw.body : '',
    publishedAt: typeof raw.published_at === 'string' ? raw.published_at : null,
    assets: assets.flatMap((asset): ReleaseAsset[] => {
      const a = asset as Record<string, unknown>

      return typeof a?.name === 'string' && typeof a.browser_download_url === 'string'
        ? [{ name: a.name, url: a.browser_download_url, size: typeof a.size === 'number' ? a.size : 0 }]
        : []
    })
  }
}

/** The NSIS setup for Windows x64: exact asset name first, then a loose match. */
export function pickWindowsSetupAsset(assets: readonly ReleaseAsset[]): ReleaseAsset | null {
  const exact = assets.find(asset => asset.name === WINDOWS_SETUP_ASSET)

  if (exact) {
    return exact
  }

  return (
    assets.find(asset => /windows/i.test(asset.name) && /x64|amd64/i.test(asset.name) && /setup.*\.exe$/i.test(asset.name)) ??
    null
  )
}

/** Short plain-text excerpt of the release body for the update card. */
export function summarizeReleaseNotes(body: string, maxChars = 700): string {
  const lines = body.replace(/\r\n?/g, '\n').split('\n')

  // The first line is usually "## Neovarch Agent X.Y.Z", already in the title.
  while (lines.length && (!lines[0].trim() || /^#{1,3}\s*neovarch/i.test(lines[0].trim()))) {
    lines.shift()
  }

  const text = lines
    .map(line => line.replace(/\*\*(.+?)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1').trimEnd())
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

  if (text.length <= maxChars) {
    return text
  }

  const cut = text.slice(0, maxChars)
  const lastBreak = cut.lastIndexOf('\n')

  return `${(lastBreak > maxChars / 2 ? cut.slice(0, lastBreak) : cut).trimEnd()}…`
}

// --------------------------------------------------------------- throttle ---

export function shouldRunStartupCheck(
  lastCheckedAt: number | null | undefined,
  now: number,
  intervalMs: number = STARTUP_CHECK_INTERVAL_MS
): boolean {
  if (typeof lastCheckedAt !== 'number' || !Number.isFinite(lastCheckedAt) || lastCheckedAt <= 0) {
    return true
  }

  // A clock that went backwards must not silence the check forever.
  if (now < lastCheckedAt) {
    return true
  }

  return now - lastCheckedAt >= intervalMs
}

// ------------------------------------------------------------ install kind ---

export type InstallKind = 'installer' | 'appimage' | 'deb' | 'windows' | 'unsupported'
export type UpdateAction = 'install-script' | 'windows-setup' | 'release-page'

export function detectInstallKind(opts: {
  platform: NodeJS.Platform
  env: Record<string, string | undefined>
  execPath: string
  homeDir: string
  isPackaged: boolean
}): InstallKind {
  if (opts.platform === 'win32') {
    return opts.isPackaged ? 'windows' : 'unsupported'
  }

  if (opts.platform !== 'linux' || !opts.isPackaged) {
    return 'unsupported'
  }

  if (opts.env.APPIMAGE) {
    return 'appimage'
  }

  const dataHome = opts.env.XDG_DATA_HOME || path.posix.join(opts.homeDir, '.local', 'share')
  const appDir = path.posix.join(dataHome, 'neovarch-agent') + '/'

  return opts.execPath.startsWith(appDir) ? 'installer' : 'deb'
}

export function updateActionFor(kind: InstallKind): UpdateAction {
  return kind === 'installer' ? 'install-script' : kind === 'windows' ? 'windows-setup' : 'release-page'
}

/**
 * The official installer for one tag, as the current user. The script is
 * downloaded to a file first so a failed download fails the run instead of
 * piping nothing into `sh` (which would "succeed"). NEOVARCH_KEEP_RUNNING
 * stops install.sh from killing this very app mid-progress; the user restarts
 * from the update card when it finishes.
 */
export function buildLinuxInstallCommand(tag: string): { command: string; args: string[]; env: Record<string, string> } {
  if (!parseSemver(tag)) {
    throw new Error(`not a release tag: ${tag}`)
  }

  const script = [
    'set -e',
    'f=$(mktemp)',
    'trap \'rm -f "$f"\' EXIT',
    'if command -v curl >/dev/null 2>&1; then curl -fsSL "$NV_INSTALL_URL" -o "$f";',
    'elif command -v wget >/dev/null 2>&1; then wget -qO "$f" "$NV_INSTALL_URL";',
    'else echo "curl atau wget tidak ditemukan / curl or wget not found" >&2; exit 127; fi',
    'sh "$f"'
  ].join('\n')

  return {
    command: '/bin/sh',
    args: ['-c', script],
    env: {
      NV_INSTALL_URL: INSTALL_SH_URL,
      NEOVARCH_VERSION: tag.startsWith('v') ? tag : `v${tag}`,
      NEOVARCH_KEEP_RUNNING: '1',
      NO_COLOR: '1'
    }
  }
}

// eslint-disable-next-line no-control-regex
const ANSI_RE = /\u001b\[[0-9;?]*[A-Za-z]|\u001b\][^\u0007]*\u0007/g

export function cleanLogChunk(chunk: string): string[] {
  return chunk
    .replace(ANSI_RE, '')
    .split(/\r?\n|\r/)
    .map(line => line.trimEnd())
    .filter(line => line.length > 0)
}

// ------------------------------------------------------------- controller ---

export interface NeovarchUpdateStatus {
  ok: boolean
  currentVersion: string
  latestVersion?: string
  releaseName?: string
  updateAvailable: boolean
  notes?: string
  releaseUrl: string
  publishedAt?: string | null
  installKind: InstallKind
  action: UpdateAction
  checkedAt?: number
  /** Quiet check answered from the 24h cache, no network request made. */
  skipped?: boolean
  error?: string
}

export type NeovarchUpdateProgress =
  | { stage: 'running'; lines: string[] }
  | { stage: 'downloading'; percent: number | null }
  | { stage: 'done' }
  | { stage: 'launched' }
  | { stage: 'error'; message: string; fellBackToReleasePage?: boolean }

export interface NeovarchApplyResult {
  ok: boolean
  action: UpdateAction
  started?: boolean
  openedReleasePage?: boolean
  error?: string
}

interface StoredState {
  lastCheckedAt?: number
  latest?: LatestRelease | null
}

interface ChildLike {
  pid?: number
  on(event: 'exit', listener: (code: number | null, signal: string | null) => void): unknown
  on(event: 'error', listener: (error: Error) => void): unknown
  unref(): void
}

export interface NeovarchUpdaterDeps {
  currentVersion: string
  statePath: string
  tmpDir: string
  installKind: InstallKind
  baseEnv: Record<string, string | undefined>
  fetch: typeof fetch
  now?: () => number
  spawn: (command: string, args: string[], options: Record<string, unknown>) => ChildLike
  openExternal: (url: string) => Promise<unknown> | unknown
  send: (progress: NeovarchUpdateProgress) => void
  quitApp: () => void
  log?: (line: string) => void
}

export function createNeovarchUpdater(deps: NeovarchUpdaterDeps) {
  const now = deps.now ?? Date.now
  const action = updateActionFor(deps.installKind)
  let latest: LatestRelease | null = null
  let applying = false

  function readState(): StoredState {
    try {
      const parsed = JSON.parse(fs.readFileSync(deps.statePath, 'utf8'))

      return parsed && typeof parsed === 'object' ? parsed : {}
    } catch {
      return {}
    }
  }

  function writeState(state: StoredState): void {
    try {
      fs.mkdirSync(path.dirname(deps.statePath), { recursive: true })
      fs.writeFileSync(deps.statePath, JSON.stringify(state))
    } catch (error) {
      deps.log?.(`[neovarch-update] could not save state: ${String(error)}`)
    }
  }

  function statusFor(release: LatestRelease | null, extra: Partial<NeovarchUpdateStatus> = {}): NeovarchUpdateStatus {
    return {
      ok: Boolean(release),
      currentVersion: deps.currentVersion,
      latestVersion: release?.tag,
      releaseName: release?.name,
      updateAvailable: release ? isNewerRelease(release.tag, deps.currentVersion) : false,
      notes: release ? summarizeReleaseNotes(release.body) : undefined,
      releaseUrl: release?.htmlUrl ?? RELEASES_PAGE,
      publishedAt: release?.publishedAt ?? null,
      installKind: deps.installKind,
      action,
      ...extra
    }
  }

  async function fetchLatest(): Promise<LatestRelease> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)

    try {
      const res = await deps.fetch(LATEST_RELEASE_API, {
        headers: { Accept: 'application/vnd.github+json', 'User-Agent': `neovarch-agent/${deps.currentVersion}` },
        signal: controller.signal
      })

      if (!res.ok) {
        throw new Error(`GitHub ${res.status}`)
      }

      const release = parseLatestRelease(await res.json())

      if (!release) {
        throw new Error('release has no valid version tag')
      }

      return release
    } finally {
      clearTimeout(timer)
    }
  }

  async function check(opts: { quiet?: boolean } = {}): Promise<NeovarchUpdateStatus> {
    const state = readState()
    const at = now()

    if (opts.quiet && !shouldRunStartupCheck(state.lastCheckedAt, at)) {
      latest = latest ?? state.latest ?? null

      return statusFor(latest, { skipped: true, checkedAt: state.lastCheckedAt, ok: Boolean(latest) })
    }

    try {
      latest = await fetchLatest()
      writeState({ lastCheckedAt: at, latest })

      return statusFor(latest, { checkedAt: at })
    } catch (error) {
      // Stamp failures too: a quiet check that fails must not retry on every launch.
      writeState({ ...state, lastCheckedAt: at })
      deps.log?.(`[neovarch-update] check failed: ${String(error)}`)

      return statusFor(null, { ok: false, checkedAt: at, error: error instanceof Error ? error.message : String(error) })
    }
  }

  async function openReleasePage(url?: string): Promise<void> {
    const target = url && url.startsWith('https://github.com/') ? url : (latest?.htmlUrl ?? RELEASES_PAGE)
    await deps.openExternal(target)
  }

  function runInstaller(tag: string): void {
    const { command, args, env } = buildLinuxInstallCommand(tag)
    fs.mkdirSync(deps.tmpDir, { recursive: true })
    const logPath = path.join(deps.tmpDir, `neovarch-update-${tag}.log`)
    const fd = fs.openSync(logPath, 'w')
    const childEnv: Record<string, string | undefined> = { ...deps.baseEnv, ...env }
    delete childEnv.ELECTRON_RUN_AS_NODE
    delete childEnv.NODE_OPTIONS

    // Detached with its output in a file: it survives this app closing.
    const child = deps.spawn(command, args, { detached: true, stdio: ['ignore', fd, fd], env: childEnv })
    fs.closeSync(fd)
    child.unref()
    deps.log?.(`[neovarch-update] installer started for ${tag} (pid ${child.pid ?? '?'}), log ${logPath}`)

    let offset = 0
    let pending = ''

    const drain = (): void => {
      try {
        const size = fs.statSync(logPath).size

        if (size <= offset) {
          return
        }

        const handle = fs.openSync(logPath, 'r')
        const buf = Buffer.alloc(size - offset)
        fs.readSync(handle, buf, 0, buf.length, offset)
        fs.closeSync(handle)
        offset = size
        const text = pending + buf.toString('utf8')
        const cut = Math.max(text.lastIndexOf('\n'), text.lastIndexOf('\r'))
        pending = cut >= 0 ? text.slice(cut + 1) : text
        const lines = cleanLogChunk(cut >= 0 ? text.slice(0, cut + 1) : '')

        if (lines.length) {
          deps.send({ stage: 'running', lines: lines.slice(-MAX_LOG_LINES) })
        }
      } catch {
        // The log is best-effort; the exit code decides the outcome.
      }
    }

    const timer = setInterval(drain, 400)

    const finish = (progress: NeovarchUpdateProgress): void => {
      clearInterval(timer)
      drain()

      if (pending.trim()) {
        deps.send({ stage: 'running', lines: cleanLogChunk(pending) })
        pending = ''
      }

      applying = false
      deps.send(progress)
    }

    child.on('error', error => finish({ stage: 'error', message: error.message }))
    child.on('exit', (code, signal) =>
      finish(
        code === 0
          ? { stage: 'done' }
          : { stage: 'error', message: signal ? `installer stopped (${signal})` : `installer exited with code ${code}` }
      )
    )
  }

  async function runWindowsSetup(release: LatestRelease): Promise<void> {
    const asset = pickWindowsSetupAsset(release.assets)

    if (!asset) {
      throw new Error(`${WINDOWS_SETUP_ASSET} is not in this release`)
    }

    deps.send({ stage: 'downloading', percent: 0 })
    const res = await deps.fetch(asset.url, { redirect: 'follow' })

    if (!res.ok || !res.body) {
      throw new Error(`download failed (HTTP ${res.status})`)
    }

    fs.mkdirSync(deps.tmpDir, { recursive: true })
    const file = path.join(deps.tmpDir, `${release.tag}-${WINDOWS_SETUP_ASSET}`)
    const total = Number(res.headers.get('content-length')) || asset.size || 0
    const out = fs.openSync(file, 'w')
    let received = 0
    let lastPercent = -1

    try {
      const reader = res.body.getReader()

      for (;;) {
        const { done, value } = await reader.read()

        if (done) {
          break
        }

        fs.writeSync(out, value)
        received += value.byteLength
        const percent = total ? Math.min(100, Math.floor((received / total) * 100)) : null

        if (percent === null || percent !== lastPercent) {
          lastPercent = percent ?? lastPercent
          deps.send({ stage: 'downloading', percent })
        }
      }
    } finally {
      fs.closeSync(out)
    }

    if (asset.size && received !== asset.size) {
      throw new Error(`download incomplete (${received} of ${asset.size} bytes)`)
    }

    const child = deps.spawn(file, [], { detached: true, stdio: 'ignore' })
    child.on('error', error => deps.log?.(`[neovarch-update] setup failed to start: ${error.message}`))
    child.unref()
    deps.log?.(`[neovarch-update] launched ${file}`)
    deps.send({ stage: 'launched' })
    // The setup replaces this app's files; close so it does not ask to.
    setTimeout(() => deps.quitApp(), 1500)
  }

  async function apply(): Promise<NeovarchApplyResult> {
    if (applying) {
      return { ok: false, action, error: 'already-running' }
    }

    if (!latest) {
      await check()
    }

    const release = latest

    if (!release) {
      return { ok: false, action, error: 'no-release' }
    }

    if (action === 'release-page' || !isNewerRelease(release.tag, deps.currentVersion)) {
      await openReleasePage(release.htmlUrl)

      return { ok: true, action, openedReleasePage: true }
    }

    applying = true

    if (action === 'install-script') {
      try {
        runInstaller(release.tag)

        return { ok: true, action, started: true }
      } catch (error) {
        applying = false
        const message = error instanceof Error ? error.message : String(error)
        deps.send({ stage: 'error', message })

        return { ok: false, action, error: message }
      }
    }

    void runWindowsSetup(release).catch(async (error: Error) => {
      applying = false
      deps.log?.(`[neovarch-update] windows setup failed: ${error.message}`)
      await openReleasePage(release.htmlUrl)
      deps.send({ stage: 'error', message: error.message, fellBackToReleasePage: true })
    })

    return { ok: true, action, started: true }
  }

  return { check, apply, openReleasePage, action }
}
