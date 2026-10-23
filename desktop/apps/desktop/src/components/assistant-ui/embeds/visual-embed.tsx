'use client'

import { type ReactNode, useEffect, useMemo, useState } from 'react'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { Zoomable } from '@/components/ui/zoomable'
import { useThemeEpoch } from '@/hooks/use-theme-epoch'
import { useI18n } from '@/i18n'
import { Copy, Download, FileImage, Maximize, MessageCode, MoreHorizontal } from '@/lib/icons'
import { copySvgAsPng, svgToPngBlob } from '@/lib/svg-image'
import { cn } from '@/lib/utils'
import {
  DEFAULT_THEME_DARK,
  DEFAULT_THEME_LIGHT,
  exportSvg,
  frameDocument,
  measureHtml,
  mermaidPartialTitle,
  partialTitle,
  prepareMermaid,
  type PreparedVisual,
  prepareVisual,
  svgCardHeight,
  type VisualTheme
} from '@/lib/visual'

import type { RichFenceProps } from './types'
import { useIsDark } from './use-is-dark'

// ```visual fences: crisp vector cards the agent draws (graph / flow / bar /
// timeline / compare specs, raw SVG, or HTML+CSS). The markup is rendered by
// lib/visual, sanitised with DOMPurify and shown in an `<iframe sandbox="">`
// (no scripts, CSP blocks every fetch). Title above, caption below, a
// "Menggambar…" placeholder while the fence streams, click for full screen,
// and a menu to view the code or save PNG/SVG.

function probeColor(className: string, prop: 'backgroundColor' | 'borderTopColor' | 'color'): string {
  const el = document.createElement('span')
  el.className = className
  el.style.cssText = 'position:absolute;left:-9999px;top:0;border-style:solid;border-width:1px'
  document.body.appendChild(el)

  try {
    return getComputedStyle(el)[prop]
  } finally {
    el.remove()
  }
}

function opaque(color: string): boolean {
  return Boolean(color) && color !== 'transparent' && !/rgba\([^)]*,\s*0\)$/.test(color) && !/\/\s*0\)$/.test(color)
}

/** The app's resolved colours, so a card blends into the chat on every theme. */
function useVisualTheme(): VisualTheme {
  const dark = useIsDark()
  const epoch = useThemeEpoch()

  return useMemo(() => {
    const base = dark ? DEFAULT_THEME_DARK : DEFAULT_THEME_LIGHT

    if (typeof document === 'undefined') {
      return base
    }

    void epoch
    const card = probeColor('bg-card', 'backgroundColor')
    const body = getComputedStyle(document.body).backgroundColor

    return {
      ...base,
      bg: opaque(card) ? card : opaque(body) ? body : base.bg,
      fg: probeColor('text-foreground', 'color') || base.fg,
      font: undefined,
      muted: probeColor('text-muted-foreground', 'color') || base.muted,
      stroke: probeColor('border-border', 'borderTopColor') || base.stroke
    }
  }, [dark, epoch])
}

// Callback ref, so the observer attaches when the body first mounts, which is
// after the fence stops streaming, not on the component's first render.
function useWidth<T extends HTMLElement>(): [(el: T | null) => void, number] {
  const [el, setEl] = useState<T | null>(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    if (!el) {
      return
    }

    setWidth(el.clientWidth)

    if (typeof ResizeObserver === 'undefined') {
      return
    }

    const ro = new ResizeObserver(entries => setWidth(Math.round(entries[0]?.contentRect.width ?? el.clientWidth)))
    ro.observe(el)

    return () => ro.disconnect()
  }, [el])

  return [setEl, width]
}

function fileName(title: string | undefined, ext: string): string {
  const slug = (title || 'visual')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48)

  return `${slug || 'visual'}.${ext}`
}

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 4000)
}

function Frame({ height, theme, visual, width }: { height: number; theme: VisualTheme; visual: PreparedVisual; width?: number }) {
  const srcDoc = useMemo(() => frameDocument(visual, theme), [visual, theme])

  return (
    <iframe
      aria-label={visual.title || 'visual'}
      className="pointer-events-none block border-0 bg-transparent"
      data-testid="visual-frame"
      sandbox=""
      srcDoc={srcDoc}
      style={{ height, width: width ?? '100%' }}
      tabIndex={-1}
      title={visual.title || 'visual'}
    />
  )
}

function Card({ children, className, source }: { children: ReactNode; className?: string; source?: string }) {
  return (
    <div
      className={cn('nv-visual-card my-2 overflow-hidden rounded-xl border border-border/70 bg-card', className)}
      data-source={source}
      data-testid="visual-card"
    >
      {children}
    </div>
  )
}

function Header({ children, title }: { children?: ReactNode; title: string }) {
  return (
    <div className="flex min-h-9 items-center gap-1 pl-3.5 pr-1.5 pt-1.5">
      <span className="min-w-0 flex-1 truncate text-[0.82rem] font-semibold text-foreground" data-testid="visual-title">
        {title}
      </span>
      {children}
    </div>
  )
}

export interface VisualRendererProps extends RichFenceProps {
  /** mermaid = an old ```mermaid / ```diagram block converted to a spec (lib/visual/mermaid.ts). */
  mode?: 'visual' | 'mermaid'
  /** Offered in the menu for converted mermaid blocks: switch to the classic mermaid drawing. */
  onClassic?: () => void
}

export default function VisualRenderer({ code, mode = 'visual', onClassic, streaming }: VisualRendererProps) {
  const { t } = useI18n()
  const s = t.nvVisual
  const fromMermaid = mode === 'mermaid'
  const prepare = fromMermaid ? prepareMermaid : prepareVisual
  const titleOf = (text: string) => (fromMermaid ? mermaidPartialTitle(text) : partialTitle(text))
  const defaultTitle = fromMermaid ? s.diagram : s.label
  const theme = useVisualTheme()
  const [bodyRef, width] = useWidth<HTMLDivElement>()
  const [showCode, setShowCode] = useState(false)
  const [full, setFull] = useState(false)
  const [notice, setNotice] = useState('')

  // Lay the spec out for the space the card body really has (minus the 14px
  // side padding of .nv-root). Bucketed so a resize doesn't re-render per pixel.
  const layoutWidth = width ? Math.max(200, Math.floor((width - 28) / 24) * 24) : 0

  const result = useMemo((): { error?: string; visual?: PreparedVisual } => {
    if (streaming) {
      return {}
    }

    try {
      return { visual: prepare(code, layoutWidth ? { width: layoutWidth } : {}) }
    } catch (error) {
      return { error: (error as Error).message || 'error' }
    }
  }, [code, streaming, layoutWidth, prepare])

  const visual = result.visual
  const maxInline = typeof window === 'undefined' ? 900 : Math.round(window.innerHeight * 0.7)

  const height = useMemo(() => {
    if (!visual || !width) {
      return 0
    }

    return visual.kind === 'svg' ? svgCardHeight(visual, width, maxInline) : Math.min(measureHtml(visual, theme, width), maxInline)
  }, [visual, width, theme, maxInline])

  useEffect(() => {
    if (!notice) {
      return
    }

    const id = window.setTimeout(() => setNotice(''), 3000)

    return () => window.clearTimeout(id)
  }, [notice])

  if (streaming) {
    return (
      <Card source={mode}>
        <Header title={titleOf(code) || defaultTitle} />
        <div aria-busy="true" className="flex h-36 items-center justify-center gap-2 text-xs text-muted-foreground" data-testid="visual-drawing">
          <span className="flex gap-1">
            <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground/60" />
            <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground/60 [animation-delay:150ms]" />
            <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground/60 [animation-delay:300ms]" />
          </span>
          {s.drawing}
        </div>
      </Card>
    )
  }

  if (!visual) {
    return (
      <Card source={mode}>
        <Header title={titleOf(code) || defaultTitle} />
        <div className="px-3.5 pt-1 text-xs text-destructive" data-testid="visual-failed" title={result.error}>
          {s.failed}
        </div>
        <pre className="overflow-auto p-3.5 font-mono text-[0.7rem] leading-relaxed whitespace-pre-wrap wrap-anywhere text-foreground/90">{code}</pre>
      </Card>
    )
  }

  const exportFor = () => {
    const htmlWidth = Math.max(320, Math.min(width || 640, 900))

    return exportSvg(visual, theme, { htmlHeight: visual.kind === 'html' ? measureHtml(visual, theme, htmlWidth) : undefined, htmlWidth })
  }

  const run = async (action: () => Promise<void> | void) => {
    try {
      await action()
    } catch {
      setNotice(s.saveFailed)
    }
  }

  const fullWidth =
    typeof window === 'undefined'
      ? 900
      : Math.round(Math.min(window.innerWidth * 0.85, visual.kind === 'svg' ? Math.max((visual.width ?? 600) * 1.6 + 28, 480) : 1100))

  const fullHeight =
    visual.kind === 'svg'
      ? svgCardHeight({ ...visual, height: (visual.height ?? 400) * 1.6, width: (visual.width ?? 600) * 1.6 }, fullWidth)
      : measureHtml(visual, theme, fullWidth)

  return (
    <Card source={mode}>
      <Header title={visual.title || defaultTitle}>
        <button
          aria-label={s.fullscreen}
          className="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          onClick={() => setFull(true)}
          type="button"
        >
          <Maximize className="size-3.5" />
        </button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              aria-label={s.options}
              className="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
              data-testid="visual-menu"
              type="button"
            >
              <MoreHorizontal className="size-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setShowCode(v => !v)}>
              {showCode ? <FileImage className="size-3.5" /> : <MessageCode className="size-3.5" />}
              {showCode ? s.viewPicture : s.viewCode}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setFull(true)}>
              <Maximize className="size-3.5" />
              {s.fullscreen}
            </DropdownMenuItem>
            {onClassic && (
              <DropdownMenuItem data-testid="visual-classic" onSelect={onClassic}>
                <FileImage className="size-3.5" />
                {s.classicStyle}
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() =>
                void run(async () => {
                  const out = exportFor()
                  download(await svgToPngBlob(out.svg, 2), fileName(visual.title, 'png'))
                })
              }
            >
              <Download className="size-3.5" />
              {s.savePng}
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() =>
                void run(() => download(new Blob([exportFor().svg], { type: 'image/svg+xml' }), fileName(visual.title, 'svg')))
              }
            >
              <Download className="size-3.5" />
              {s.saveSvg}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void run(() => copySvgAsPng(exportFor().svg))}>
              <FileImage className="size-3.5" />
              {s.copyImage}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void run(() => navigator.clipboard.writeText(code))}>
              <Copy className="size-3.5" />
              {s.copyCode}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </Header>
      <div ref={bodyRef}>
        {showCode ? (
          <pre className="max-h-[60vh] overflow-auto p-3.5 font-mono text-[0.7rem] leading-relaxed whitespace-pre-wrap wrap-anywhere text-foreground/90" data-testid="visual-code">
            {code}
          </pre>
        ) : (
          <Zoomable
            label={s.fullscreen}
            onCopy={() => run(() => copySvgAsPng(exportFor().svg))}
            onOpenChange={setFull}
            open={full}
            overlay={<Frame height={fullHeight} theme={theme} visual={visual} width={fullWidth} />}
          >
            {height ? <Frame height={height} theme={theme} visual={visual} /> : <div className="h-24" />}
          </Zoomable>
        )}
      </div>
      {(visual.caption || notice) && (
        <div className="px-3.5 pb-3 text-[0.78rem] leading-snug text-muted-foreground" data-testid="visual-caption">
          {notice ? <span className="text-destructive">{notice}</span> : visual.caption}
        </div>
      )}
    </Card>
  )
}
