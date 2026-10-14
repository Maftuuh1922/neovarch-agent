// "Bagikan kartu" on the Kantor page (Pamerkan): preview the Kartu Neovarch,
// pick theme / layout / background / format / period, hide or show widgets
// (radar, bar, donut, trend, usage tiles, office stats, Kantor 3D, model) and
// export: Simpan PNG / Salin gambar / open X, Facebook or WhatsApp Web with
// the landing link. Choices persist (pamerkan-prefs.ts); chart numbers come
// only from GET /api/pamerkan (this PC's own sessions + token counter).
import { useStore } from '@nanostores/react'
import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useI18n } from '@/i18n'
import { openExternalLink } from '@/lib/external-link'

import { $nvAppearance, DEFAULT_ACCENT } from './appearance'
import { captureOffice3D, NEOVARCH_LANDING_URL, planShareCard, renderShareCardPng, type ShareCardFormat, shareLinks, statsFromOffice } from './kartu-card'
import { $office } from './office-store'
import type { ChartBlock } from './pamerkan-card'
import {
  loadPamerkanPrefs,
  PAMERKAN_BACKGROUNDS,
  PAMERKAN_LAYOUTS,
  PAMERKAN_THEMES,
  PAMERKAN_WIDGETS,
  PAMERKAN_WINDOWS,
  type PamerkanPrefs,
  type PamerkanWidget,
  savePamerkanPrefs
} from './pamerkan-prefs'
import { $pamerkan, $pamerkanState, refreshPamerkan } from './pamerkan-store'

const NAME_KEY = 'nv.shareCard.name'
const HANDLE_KEY = 'nv.shareCard.handle'

function readPref(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

function writePref(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // private mode / storage off: the card still works
  }
}

export function KartuCardButton() {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [shot, setShot] = useState<null | string>(null)

  const start = async () => {
    setShot(await captureOffice3D())
    setOpen(true)
  }

  return (
    <>
      <button className="nv-office-open" data-slot="nv-kartu-open" onClick={() => void start()} type="button">
        {t.nvPamerkan.open}
      </button>
      <KartuCardDialog officeShot={shot} onOpenChange={setOpen} open={open} />
    </>
  )
}

function Segmented<T extends number | string>({
  label,
  onChange,
  options,
  slot,
  value
}: {
  label: string
  onChange: (v: T) => void
  options: { label: string; value: T }[]
  slot: string
  value: T
}) {
  return (
    <div className="nv-kartu-group">
      <span className="nv-kartu-group-label">{label}</span>
      <div aria-label={label} className="nv-office-view-toggle nv-kartu-seg" data-slot={slot} role="group">
        {options.map(o => (
          <button aria-pressed={value === o.value} key={String(o.value)} onClick={() => onChange(o.value)} type="button">
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}

export function KartuCardDialog({ officeShot, onOpenChange, open }: { officeShot: null | string; onOpenChange: (open: boolean) => void; open: boolean }) {
  const { locale, t } = useI18n()
  const p = t.nvPamerkan
  const office = useStore($office)
  const appearance = useStore($nvAppearance)
  const pamerkan = useStore($pamerkan)
  const pkState = useStore($pamerkanState)
  const [prefs, setPrefs] = useState<PamerkanPrefs>(() => loadPamerkanPrefs())
  const [format, setFormat] = useState<ShareCardFormat>('story')
  const [name, setName] = useState(() => readPref(NAME_KEY))
  const [handle, setHandle] = useState(() => readPref(HANDLE_KEY))
  const [png, setPng] = useState<Blob | null>(null)
  const [url, setUrl] = useState<null | string>(null)
  const [note, setNote] = useState<null | string>(null)

  const update = (patch: Partial<PamerkanPrefs>) =>
    setPrefs(prev => {
      const next = { ...prev, ...patch }
      savePamerkanPrefs(next)

      return next
    })

  const toggleWidget = (w: PamerkanWidget) => update({ widgets: { ...prefs.widgets, [w]: !prefs.widgets[w] } })

  useEffect(() => {
    if (open) {
      void refreshPamerkan(prefs.days)
    }
  }, [open, prefs.days])

  const data = useMemo(
    () => ({ handle, link: NEOVARCH_LANDING_URL, name, officeShot, stats: statsFromOffice(office) }),
    [handle, name, officeShot, office]
  )

  const opts = useMemo(
    () => ({
      accent: appearance?.accent || DEFAULT_ACCENT,
      background: prefs.background,
      format,
      labels: p.card,
      layout: prefs.layout,
      locale,
      pamerkan: pamerkan && pamerkan.days === prefs.days ? pamerkan : null,
      showOffice: Boolean(officeShot),
      showStats: true,
      style: prefs.theme,
      text: p.card,
      trend: prefs.trend,
      widgets: prefs.widgets
    }),
    [appearance?.accent, prefs, format, p.card, locale, pamerkan, officeShot]
  )

  const dropped: ChartBlock[] = useMemo(() => (open ? planShareCard(data, opts).dropped : []), [open, data, opts])

  useEffect(() => {
    if (!open) {
      return
    }

    let cancelled = false
    renderShareCardPng(data, opts)
      .then(blob => {
        if (!cancelled) {
          setPng(blob)
        }
      })
      .catch(e => !cancelled && setNote(p.renderFailed.replace('{error}', e instanceof Error ? e.message : String(e))))

    return () => {
      cancelled = true
    }
  }, [open, data, opts, p.renderFailed])

  useEffect(() => {
    if (!png) {
      return
    }

    const u = URL.createObjectURL(png)
    setUrl(u)

    return () => URL.revokeObjectURL(u)
  }, [png])

  const save = () => {
    if (!url) {
      return
    }

    const a = document.createElement('a')
    a.href = url
    a.download = `kartu-neovarch-${format}.png`
    a.click()
    setNote(p.saved)
  }

  const copy = async () => {
    try {
      if (!png || typeof ClipboardItem === 'undefined') {
        throw new Error('clipboard image unavailable')
      }

      await navigator.clipboard.write([new ClipboardItem({ 'image/png': png })])
      setNote(p.copied)
    } catch (e) {
      setNote(p.copyFailed.replace('{error}', e instanceof Error ? e.message : String(e)))
    }
  }

  const blockName = (b: ChartBlock) => (b === 'row' ? `${p.widgets.bars} + ${p.widgets.donut}` : p.widgets[b])

  const status =
    pkState === 'loading' && !pamerkan ? p.loading : pkState === 'error' && !pamerkan ? p.unavailable : pamerkan?.empty ? p.empty : null

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="nv-kartu-dialog" data-slot="nv-kartu-dialog">
        <DialogHeader>
          <DialogTitle>{p.title}</DialogTitle>
          <DialogDescription>{p.description}</DialogDescription>
        </DialogHeader>

        <div className="nv-kartu-body">
          <div className="nv-kartu-preview" data-format={format}>
            {url ? <img alt={p.previewAlt} data-slot="nv-kartu-preview" src={url} /> : <p>{p.rendering}</p>}
          </div>

          <div className="nv-kartu-controls">
            <Segmented
              label={p.sections.theme}
              onChange={v => update({ theme: v })}
              options={PAMERKAN_THEMES.map(v => ({ label: p.themes[v], value: v }))}
              slot="nv-kartu-theme"
              value={prefs.theme}
            />
            <Segmented
              label={p.sections.layout}
              onChange={v => update({ layout: v })}
              options={PAMERKAN_LAYOUTS.map(v => ({ label: p.layouts[v], value: v }))}
              slot="nv-kartu-layout"
              value={prefs.layout}
            />
            <Segmented
              label={p.sections.background}
              onChange={v => update({ background: v })}
              options={PAMERKAN_BACKGROUNDS.map(v => ({ label: p.backgrounds[v], value: v }))}
              slot="nv-kartu-background"
              value={prefs.background}
            />
            <Segmented
              label={p.sections.format}
              onChange={setFormat}
              options={(['story', 'feed'] as const).map(v => ({ label: p.formats[v], value: v }))}
              slot="nv-kartu-format"
              value={format}
            />
            <Segmented
              label={p.sections.window}
              onChange={v => update({ days: v })}
              options={PAMERKAN_WINDOWS.map(v => ({ label: p.windowDays.replace('{days}', String(v)), value: v }))}
              slot="nv-kartu-window"
              value={prefs.days}
            />
            <Segmented
              label={p.sections.trend}
              onChange={v => update({ trend: v })}
              options={(['daily', 'weekly'] as const).map(v => ({ label: p.trendModes[v], value: v }))}
              slot="nv-kartu-trend"
              value={prefs.trend}
            />

            <fieldset className="nv-kartu-widgets" data-slot="nv-kartu-widgets">
              <legend>{p.sections.widgets}</legend>
              {PAMERKAN_WIDGETS.map(w => (
                <label className="nv-kartu-check" key={w}>
                  <input checked={prefs.widgets[w]} data-widget={w} onChange={() => toggleWidget(w)} type="checkbox" /> {p.widgets[w]}
                </label>
              ))}
            </fieldset>

            {status && (
              <p className="nv-kartu-note" data-slot="nv-kartu-data-note">
                {status}
              </p>
            )}
            {dropped.length > 0 && (
              <p className="nv-kartu-note" data-slot="nv-kartu-dropped">
                {p.dropped.replace('{list}', dropped.map(blockName).join(', '))}
              </p>
            )}

            <label className="nv-kartu-field">
              <span>{p.nameLabel}</span>
              <input
                maxLength={32}
                onChange={e => {
                  setName(e.target.value)
                  writePref(NAME_KEY, e.target.value)
                }}
                placeholder={p.card.defaultName}
                value={name}
              />
            </label>
            <label className="nv-kartu-field">
              <span>{p.handleLabel}</span>
              <input
                maxLength={40}
                onChange={e => {
                  setHandle(e.target.value)
                  writePref(HANDLE_KEY, e.target.value)
                }}
                placeholder="@username"
                value={handle}
              />
            </label>
            {!officeShot && prefs.widgets.office && <p className="nv-kartu-note">{p.officeHint}</p>}
            <p className="nv-kartu-note nv-kartu-privacy">{p.privacy}</p>

            <div className="nv-kartu-actions">
              <Button data-slot="nv-kartu-save" disabled={!url} onClick={save} size="sm">
                {p.save}
              </Button>
              <Button data-slot="nv-kartu-copy" disabled={!png} onClick={() => void copy()} size="sm" variant="secondary">
                {p.copy}
              </Button>
            </div>
            <div className="nv-kartu-actions">
              {shareLinks(NEOVARCH_LANDING_URL, p.shareText).map(l => (
                <Button key={l.label} onClick={() => openExternalLink(l.url)} size="sm" variant="outline">
                  {l.label}
                </Button>
              ))}
            </div>
            {note && (
              <p className="nv-kartu-note" role="status">
                {note}
              </p>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
