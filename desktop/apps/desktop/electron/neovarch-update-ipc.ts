/**
 * IPC for Neovarch's GitHub-Releases updater (neovarch:update:*). The renderer
 * reaches it through the `neovarchUpdate` preload global.
 */
import { spawn, type SpawnOptions } from 'node:child_process'
import os from 'node:os'
import path from 'node:path'

import { app, BrowserWindow, ipcMain, shell } from 'electron'

import {
  createNeovarchUpdater,
  detectInstallKind,
  type NeovarchUpdateProgress,
  type NeovarchUpdateStatus
} from './neovarch-update'

export const NEOVARCH_UPDATE_PROGRESS_CHANNEL = 'neovarch:update:progress'

export function registerNeovarchUpdateIpc(opts: {
  log?: (line: string) => void
  /** Restart the app the way the rest of main does (backend shutdown first). */
  relaunch: () => void
}): void {
  const installKind = detectInstallKind({
    platform: process.platform,
    env: process.env,
    execPath: process.execPath,
    homeDir: os.homedir(),
    isPackaged: app.isPackaged
  })

  const send = (progress: NeovarchUpdateProgress): void => {
    for (const win of BrowserWindow.getAllWindows()) {
      if (!win.isDestroyed()) {
        win.webContents.send(NEOVARCH_UPDATE_PROGRESS_CHANNEL, progress)
      }
    }
  }

  const updater = createNeovarchUpdater({
    currentVersion: app.getVersion(),
    statePath: path.join(app.getPath('userData'), 'neovarch-update.json'),
    tmpDir: path.join(app.getPath('temp'), 'neovarch-update'),
    installKind,
    baseEnv: process.env,
    fetch: globalThis.fetch.bind(globalThis),
    spawn: (command, args, options) => spawn(command, args, options as SpawnOptions),
    openExternal: url => shell.openExternal(url),
    send,
    quitApp: () => app.quit(),
    log: opts.log
  })

  ipcMain.handle(
    'neovarch:update:check',
    (_event, payload?: { quiet?: boolean }): Promise<NeovarchUpdateStatus> =>
      updater.check({ quiet: Boolean(payload?.quiet) })
  )
  ipcMain.handle('neovarch:update:apply', () => updater.apply())
  ipcMain.handle('neovarch:update:open-release', (_event, url?: unknown) =>
    updater.openReleasePage(typeof url === 'string' ? url : undefined)
  )
  ipcMain.handle('neovarch:update:relaunch', () => opts.relaunch())
}
