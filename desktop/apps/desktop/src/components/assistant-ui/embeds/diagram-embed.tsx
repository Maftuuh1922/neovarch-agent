'use client'

import { useMemo, useState } from 'react'

import { useI18n } from '@/i18n'
import { FileImage } from '@/lib/icons'
import { looksLikeVisualBody, prepareMermaid } from '@/lib/visual'

import MermaidRenderer from './mermaid-embed'
import type { RichFenceProps } from './types'
import VisualRenderer from './visual-embed'

// Old diagram blocks (```mermaid, ```mmd, ```diagram) in the visual-inline
// style. Mermaid flowcharts, sequence diagrams, timelines, pies and simple
// state diagrams are converted to ```visual specs (lib/visual/mermaid.ts) and
// drawn by the same card as ```visual blocks: title above, crisp vector body,
// caption, full screen, save PNG/SVG. Anything the converter does not
// understand keeps the classic mermaid drawing, so old messages always render.
// A ```diagram fence holding a ```visual body (JSON / SVG / HTML) is a visual.

function canDrawAsVisual(code: string): boolean {
  try {
    prepareMermaid(code)

    return true
  } catch {
    return false
  }
}

export default function DiagramRenderer({ code, streaming }: RichFenceProps) {
  const { t } = useI18n()
  const s = t.nvVisual
  const [classic, setClassic] = useState(false)
  const visualBody = looksLikeVisualBody(code)
  const convertible = useMemo(() => !streaming && !visualBody && canDrawAsVisual(code), [code, streaming, visualBody])

  if (visualBody) {
    return <VisualRenderer code={code} streaming={streaming} />
  }

  // While the fence streams, show the same "Menggambar…" card as ```visual.
  if (streaming) {
    return <VisualRenderer code={code} mode="mermaid" streaming />
  }

  if (convertible && !classic) {
    return <VisualRenderer code={code} mode="mermaid" onClassic={() => setClassic(true)} />
  }

  if (convertible) {
    return (
      <div className="my-2 overflow-hidden rounded-xl border border-border/70 bg-card" data-testid="diagram-classic">
        <div className="flex min-h-9 items-center gap-1 pl-3.5 pr-1.5 pt-1.5">
          <span className="min-w-0 flex-1 truncate text-[0.82rem] font-semibold text-muted-foreground">{s.classicStyle}</span>
          <button
            className="flex h-7 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
            data-testid="diagram-new-style"
            onClick={() => setClassic(false)}
            type="button"
          >
            <FileImage className="size-3.5" />
            {s.newStyle}
          </button>
        </div>
        <MermaidRenderer code={code} />
      </div>
    )
  }

  return (
    <div data-testid="diagram-fallback">
      <MermaidRenderer code={code} />
    </div>
  )
}
