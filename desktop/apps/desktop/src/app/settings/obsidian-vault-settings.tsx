import { useCallback, useEffect, useState } from 'react'

import { hermesApi } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Brain, FolderOpen } from '@/lib/icons'

import { ListRow, SectionHeading, SettingsContent, ToggleRow } from './primitives'

// Settings ▸ Memori & Skill ▸ Vault Obsidian — the one place the Obsidian vault
// folder (core config `memory.obsidian_vault` + `memory.obsidian_enabled`) is
// chosen. Saved through POST /api/memory/obsidian, which validates the folder
// on the core side; the /vault page reads the same config.

export interface ObsidianVaultStatus {
  configured: boolean
  connected: boolean
  enabled?: boolean
  error?: string
  note_count: number
  path: string
}

export const OBSIDIAN_STATUS_PATH = '/api/memory/obsidian'

/** Event the /vault page listens for so it reloads right after a save. */
export const OBSIDIAN_VAULT_CHANGED_EVENT = 'neovarch:obsidian-vault-changed'

const CAPTION = 'text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)'

function errorText(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e)
  const match = raw.match(/"error"\s*:\s*"([^"]+)"/)

  return match ? match[1] : raw
}

export function ObsidianVaultSettings() {
  const [status, setStatus] = useState<ObsidianVaultStatus | null>(null)
  const [path, setPath] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<null | string>(null)
  const [saved, setSaved] = useState(false)

  const apply = useCallback((st: ObsidianVaultStatus) => {
    setStatus(st)
    setPath(st.path || '')
    setEnabled(st.enabled !== false)
  }, [])

  useEffect(() => {
    let alive = true

    hermesApi<ObsidianVaultStatus>({ path: OBSIDIAN_STATUS_PATH })
      .then(st => alive && apply(st))
      .catch(e => alive && setError(errorText(e)))

    return () => {
      alive = false
    }
  }, [apply])

  const pick = useCallback(async () => {
    const picked = await window.hermesDesktop?.selectPaths?.({
      defaultPath: path || undefined,
      directories: true,
      title: 'Pilih folder vault Obsidian'
    })

    if (picked?.[0]) {
      setPath(picked[0])
      setSaved(false)
      setError(null)
    }
  }, [path])

  const dirty = status !== null && (path.trim() !== (status.path || '') || enabled !== (status.enabled !== false))

  const save = useCallback(async () => {
    setSaving(true)
    setError(null)

    try {
      const st = await hermesApi<ObsidianVaultStatus>({
        body: { enabled, path: path.trim() },
        method: 'POST',
        path: OBSIDIAN_STATUS_PATH
      })

      apply(st)
      setSaved(true)
      window.dispatchEvent(new CustomEvent(OBSIDIAN_VAULT_CHANGED_EVENT, { detail: st }))
    } catch (e) {
      setError(errorText(e))
    } finally {
      setSaving(false)
    }
  }, [apply, enabled, path])

  const state = !status
    ? 'Memuat…'
    : status.configured && status.connected
      ? `Tersambung · ${status.note_count} catatan`
      : status.configured
        ? `Folder tidak bisa dibuka${status.error ? ` (${status.error})` : ''}`
        : status.path && status.enabled === false
          ? 'Nonaktif'
          : 'Belum ada vault'

  return (
    <SettingsContent>
      <div data-nv-settings="obsidian">
        <SectionHeading icon={Brain} meta={state} title="Vault Obsidian" />
        <p className={CAPTION}>
          Folder catatan Obsidian yang dipakai Neovarch sebagai memori jangka panjang. Agen membaca dan menulis catatan
          di sini; halaman Vault Obsidian menampilkannya.
        </p>
        <ToggleRow
          checked={enabled}
          description="Matikan untuk berhenti memakai vault tanpa menghapus folder yang dipilih."
          label="Pakai vault Obsidian"
          onChange={on => {
            setEnabled(on)
            setSaved(false)
          }}
        />
        <ListRow
          action={
            <Button data-nv-obsidian-pick onClick={() => void pick()} size="sm" type="button" variant="outline">
              <FolderOpen className="size-3.5" /> Pilih folder…
            </Button>
          }
          below={
            <Input
              aria-label="Folder vault"
              className="mt-2 font-mono text-xs"
              data-nv-obsidian-path
              onChange={e => {
                setPath(e.target.value)
                setSaved(false)
              }}
              placeholder="/home/kamu/Obsidian/Vault"
              value={path}
            />
          }
          description="Folder yang berisi catatan .md (biasanya ada folder .obsidian di dalamnya)."
          title="Folder vault"
        />
        <div className="flex items-center gap-3 py-3">
          <Button data-nv-obsidian-save disabled={saving || !dirty} onClick={() => void save()} type="button">
            {saving ? 'Menyimpan…' : 'Simpan'}
          </Button>
          {saved && !dirty && <span className={CAPTION}>Tersimpan.</span>}
          {error && (
            <span className="text-[length:var(--conversation-caption-font-size)] text-destructive" role="alert">
              {error}
            </span>
          )}
        </div>
      </div>
    </SettingsContent>
  )
}
