import { useCallback, useEffect, useRef, useState } from 'react'

import { hermesApi } from '@/api/client'

/** Optional extras (Obsidian first): status, install with progress, auto-install toggle.
 *  The core downloads the official build (obsidian.md / GitHub releases of
 *  obsidianmd/obsidian-releases) — Obsidian is never bundled with Neovarch. The
 *  built-in vault graph works without it. */

export interface ExtraStatus {
  auto?: boolean
  homepage?: string
  installed: boolean
  label?: string
  last?: null | { status?: string; ts?: number }
  name: string
  path?: null | string
  platform?: string
  purpose?: string
}

export interface ExtrasJob {
  detail?: string
  name?: string
  percent?: null | number
  phase?: string
  state: 'done' | 'ensured' | 'failed' | 'running'
  status?: string
}

interface ExtrasResponse {
  extras: ExtraStatus[]
  job: ExtrasJob | null
}

export const EXTRAS_PATH = '/api/extras'

export function extrasPhaseText(job: ExtrasJob | null): string {
  if (!job) {
    return ''
  }

  if (job.state === 'failed') {
    return `Gagal memasang${job.detail ? `: ${job.detail}` : ''}`
  }

  if (job.state === 'done') {
    return job.status === 'opened'
      ? 'Penginstal dibuka — seret Obsidian ke Applications.'
      : job.status === 'unsupported'
        ? 'Belum ada build resmi untuk sistem ini — unduh dari obsidian.md.'
        : 'Obsidian terpasang.'
  }

  if (job.phase === 'download') {
    return `Mengunduh dari rilis resmi… ${job.percent != null ? `${Math.round(job.percent)}%` : ''}`.trim()
  }

  if (job.phase === 'install') {
    return 'Memasang…'
  }

  return 'Menyiapkan…'
}

export function useExtras(pollMs = 800) {
  const [extras, setExtras] = useState<ExtraStatus[] | null>(null)
  const [job, setJob] = useState<ExtrasJob | null>(null)
  const [error, setError] = useState<null | string>(null)
  const timer = useRef<null | ReturnType<typeof setTimeout>>(null)

  const refresh = useCallback(async () => {
    try {
      const res = await hermesApi<ExtrasResponse>({ path: EXTRAS_PATH })
      setExtras(res.extras ?? [])
      setJob(res.job ?? null)
      setError(null)

      return res
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))

      return null
    }
  }, [])

  useEffect(() => {
    void refresh()

    return () => {
      if (timer.current) {
        clearTimeout(timer.current)
      }
    }
  }, [refresh])

  // poll while an install runs
  useEffect(() => {
    if (job?.state !== 'running') {
      return
    }

    timer.current = setTimeout(() => void refresh(), pollMs)

    return () => {
      if (timer.current) {
        clearTimeout(timer.current)
      }
    }
  }, [job, pollMs, refresh])

  const install = useCallback(
    async (name = 'obsidian') => {
      try {
        const res = await hermesApi<{ job: ExtrasJob }>({ body: { name }, method: 'POST', path: `${EXTRAS_PATH}/install` })
        setJob(res.job ?? { state: 'running' })
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    },
    []
  )

  const setAuto = useCallback(
    async (on: boolean) => {
      await hermesApi({ body: { extras: { auto_install: on } }, method: 'PUT', path: '/api/config' })
      await refresh()
    },
    [refresh]
  )

  return { error, extras, install, job, refresh, setAuto }
}

/** Settings ▸ Vault Obsidian ▸ Ekstra opsional. */
export function ObsidianExtraPanel() {
  const { error, extras, install, job, setAuto } = useExtras()
  const ob = extras?.find(e => e.name === 'obsidian')
  const running = job?.state === 'running'

  return (
    <div className="nv-extras" data-nv-extras>
      <div className="nv-extras-row">
        <div>
          <strong>Obsidian (opsional)</strong>
          <p className="nv-extras-caption">
            {!ob
              ? 'Memeriksa…'
              : ob.installed
                ? `Terpasang${ob.path ? ` · ${ob.path}` : ''}`
                : 'Belum terpasang. Graf vault bawaan tetap jalan; Obsidian dipasang otomatis saat instalasi/pembaruan, atau sekarang.'}
          </p>
        </div>
        {ob && !ob.installed && (
          <button
            className="nv-vault-btn"
            data-nv-extras-install
            disabled={running}
            onClick={() => void install('obsidian')}
            type="button"
          >
            {running ? 'Memasang…' : 'Pasang Obsidian'}
          </button>
        )}
      </div>
      {job && job.name !== undefined && (
        <div className="nv-extras-progress" data-nv-extras-progress role="status">
          {running && (
            <div className="nv-extras-bar">
              <span style={{ width: `${job.percent ?? 8}%` }} />
            </div>
          )}
          <span className="nv-extras-caption">{extrasPhaseText(job)}</span>
        </div>
      )}
      {ob && (
        <label className="nv-extras-auto">
          <input checked={ob.auto !== false} onChange={e => void setAuto(e.target.checked)} type="checkbox" /> Pasang
          ekstra yang belum ada secara otomatis saat instalasi & pembaruan (dari sumber resmi, tidak dibundel)
        </label>
      )}
      {error && (
        <p className="nv-extras-caption" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

/** "Buka di Obsidian": open the link when Obsidian is installed; otherwise offer to install
 *  it (official build, with progress) and open once it is there. */
export function useOpenInObsidian() {
  const { extras, install, job, refresh } = useExtras()
  const [offer, setOffer] = useState<null | string>(null)
  const pending = useRef<null | string>(null)

  const openNow = useCallback((uri: string) => {
    void window.hermesDesktop?.openExternal?.(uri)
  }, [])

  const open = useCallback(
    async (uri: string) => {
      const ob = (await refresh())?.extras.find(e => e.name === 'obsidian') ?? extras?.find(e => e.name === 'obsidian')

      if (!ob || ob.installed) {
        openNow(uri)

        return
      }

      setOffer(uri)
    },
    [extras, openNow, refresh]
  )

  const accept = useCallback(async () => {
    pending.current = offer
    setOffer(null)
    await install('obsidian')
  }, [install, offer])

  useEffect(() => {
    if (job?.state === 'done' && job.status === 'installed' && pending.current) {
      openNow(pending.current)
      pending.current = null
    }
  }, [job, openNow])

  return { accept, dismiss: () => setOffer(null), job, offer, open }
}
