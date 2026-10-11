// "Jalankan di latar belakang" (Settings ▸ Remote).
//
// When on, the LAN gateway and its relay client keep running after the window
// is closed: the window hides to the tray, the gateway is started detached with
// its output in a log file (no pipe tied to Electron), and quitting the app
// leaves it running. "Mulai saat login" starts Neovarch hidden at login
// (Linux: XDG autostart entry; Windows/macOS: the OS login item).
//
// The same two settings live in the gateway (core/neovarch/background.py,
// GET/POST /api/remote/background) so the phone can change them; whichever side
// changed last (updated_at) wins. Pure logic here so it stays unit-testable.

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export const HIDDEN_ARG = '--hidden'
export const AUTOSTART_FILE = 'neovarch-agent.desktop'

export interface BackgroundSettings {
  runInBackground: boolean
  startAtLogin: boolean
  /** unix seconds of the last change (desktop or phone) */
  updatedAt: number
}

/** What GET /api/remote/background returns (core/neovarch/background.py). */
export interface CoreBackgroundStatus {
  run_in_background: boolean
  start_at_login: boolean
  updated_at: number
  service?: { state: string; mode: string; desktop_attached: boolean; pid: number; port: number; uptime_s: number }
  agent?: { sessions: number; running: number }
  relay?: { enabled: boolean; state: string; phones: number; error: string | null }
}

export interface BackgroundStatus extends BackgroundSettings {
  /** a tray icon is available, so closing the window can hide it */
  trayAvailable: boolean
  /** autostart is supported on this platform */
  autostartSupported: boolean
  /** what the gateway reports (null when it is not running) */
  service: CoreBackgroundStatus['service'] | null
  agent: CoreBackgroundStatus['agent'] | null
  error: string | null
}

export const defaultBackgroundSettings = (): BackgroundSettings => ({
  runInBackground: false,
  startAtLogin: false,
  updatedAt: 0
})

export function parseBackgroundSettings(raw: unknown): BackgroundSettings {
  const base = defaultBackgroundSettings()

  if (!raw || typeof raw !== 'object') {
    return base
  }

  const r = raw as Record<string, unknown>

  return {
    runInBackground: r.runInBackground === true,
    startAtLogin: r.startAtLogin === true,
    updatedAt: typeof r.updatedAt === 'number' && Number.isFinite(r.updatedAt) && r.updatedAt > 0 ? r.updatedAt : 0
  }
}

export function readBackgroundSettings(file: string): BackgroundSettings {
  try {
    return parseBackgroundSettings(JSON.parse(fs.readFileSync(file, 'utf8')))
  } catch {
    return defaultBackgroundSettings()
  }
}

export function writeBackgroundSettings(file: string, s: BackgroundSettings) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, JSON.stringify(s, null, 2), { encoding: 'utf8', mode: 0o600 })
}

/**
 * Merge the gateway's copy into ours: the newer side wins. Returns the merged
 * settings and whether the gateway must be told (ours is newer).
 */
export function mergeWithCore(
  local: BackgroundSettings,
  core: Pick<CoreBackgroundStatus, 'run_in_background' | 'start_at_login' | 'updated_at'> | null
): { settings: BackgroundSettings; pushToCore: boolean; changed: boolean } {
  if (!core) {
    return { settings: local, pushToCore: false, changed: false }
  }

  const same = core.run_in_background === local.runInBackground && core.start_at_login === local.startAtLogin

  if (same) {
    return { settings: local, pushToCore: false, changed: false }
  }

  if ((core.updated_at || 0) > local.updatedAt) {
    return {
      settings: { runInBackground: core.run_in_background, startAtLogin: core.start_at_login, updatedAt: core.updated_at },
      pushToCore: false,
      changed: true
    }
  }

  return { settings: local, pushToCore: true, changed: false }
}

/** Closing the main window: hide to the tray, or the ordinary close. */
export function closeAction(s: Pick<BackgroundSettings, 'runInBackground'>, trayAvailable: boolean): 'hide' | 'close' {
  return s.runInBackground && trayAvailable ? 'hide' : 'close'
}

/**
 * Quitting the app: stop the LAN gateway, or leave it running on its own.
 * `stopEverything` is the tray's "Hentikan semua & keluar".
 */
export function quitGatewayAction(
  s: Pick<BackgroundSettings, 'runInBackground'>,
  remoteEnabled: boolean,
  stopEverything = false
): 'stop' | 'detach' {
  return s.runInBackground && remoteEnabled && !stopEverything ? 'detach' : 'stop'
}

/** Whether this launch should start without showing the window. */
export function launchedHidden(argv: readonly string[]): boolean {
  return argv.includes(HIDDEN_ARG)
}

export function autostartSupported(platform: NodeJS.Platform): boolean {
  return platform === 'linux' || platform === 'win32' || platform === 'darwin'
}

/** How to start this install again: the AppImage path when running from one. */
export function launchCommand(execPath: string, env: NodeJS.ProcessEnv = process.env): string {
  return env.APPIMAGE && env.APPIMAGE.trim() ? env.APPIMAGE : execPath
}

function desktopExecQuote(arg: string): string {
  // XDG Desktop Entry Exec quoting: wrap in double quotes, escape " ` $ \
  return /[\s"'\\`$]/.test(arg) ? `"${arg.replace(/(["`$\\])/g, '\\$1')}"` : arg
}

export function linuxAutostartEntry(command: string): string {
  return [
    '[Desktop Entry]',
    'Type=Application',
    'Name=Neovarch Agent',
    'Comment=Neovarch berjalan di latar belakang (gateway & relay untuk HP)',
    `Exec=${desktopExecQuote(command)} ${HIDDEN_ARG}`,
    'Icon=neovarch-agent',
    'Terminal=false',
    'X-GNOME-Autostart-enabled=true',
    'NoDisplay=false',
    ''
  ].join('\n')
}

export function linuxAutostartPath(env: NodeJS.ProcessEnv = process.env, home = os.homedir()): string {
  const base = env.XDG_CONFIG_HOME && env.XDG_CONFIG_HOME.trim() ? env.XDG_CONFIG_HOME : path.join(home, '.config')

  return path.join(base, 'autostart', AUTOSTART_FILE)
}

export interface LoginItemApi {
  setLoginItemSettings: (s: { openAtLogin: boolean; openAsHidden?: boolean; path?: string; args?: string[] }) => void
}

/** Apply "Mulai saat login". Returns an Indonesian error message or null. */
export function applyStartAtLogin(opts: {
  enabled: boolean
  platform: NodeJS.Platform
  execPath: string
  env?: NodeJS.ProcessEnv
  home?: string
  app?: LoginItemApi
  fsImpl?: Pick<typeof fs, 'mkdirSync' | 'writeFileSync' | 'rmSync'>
}): string | null {
  const f = opts.fsImpl ?? fs
  const env = opts.env ?? process.env

  try {
    if (opts.platform === 'linux') {
      const file = linuxAutostartPath(env, opts.home)

      if (opts.enabled) {
        f.mkdirSync(path.dirname(file), { recursive: true })
        f.writeFileSync(file, linuxAutostartEntry(launchCommand(opts.execPath, env)), { encoding: 'utf8', mode: 0o644 })
      } else {
        f.rmSync(file, { force: true })
      }

      return null
    }

    if (opts.platform === 'win32' || opts.platform === 'darwin') {
      if (!opts.app) {
        return 'Mulai saat login tidak tersedia.'
      }

      opts.app.setLoginItemSettings({
        openAtLogin: opts.enabled,
        openAsHidden: opts.enabled,
        path: opts.platform === 'win32' ? opts.execPath : undefined,
        args: opts.enabled ? [HIDDEN_ARG] : []
      })

      return null
    }

    return 'Mulai saat login belum didukung di sistem ini.'
  } catch (err) {
    return `Gagal mengatur mulai saat login: ${(err as Error).message}`
  }
}

/** Indonesian one-liner for the settings screen. */
export function serviceLabel(st: Pick<BackgroundStatus, 'runInBackground' | 'service'>): string {
  if (!st.service) {
    return st.runInBackground ? 'Aktif — gateway belum berjalan' : 'Mati'
  }

  if (st.service.state === 'stopping') {
    return 'Sedang dihentikan'
  }

  if (st.service.state === 'restarting') {
    return 'Sedang dimulai ulang'
  }

  return st.runInBackground ? 'Berjalan di latar belakang' : 'Berjalan (ikut jendela aplikasi)'
}
