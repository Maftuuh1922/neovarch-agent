import { useStore } from '@nanostores/react'
import { useEffect } from 'react'

import type { UsageStats } from '@/types/hermes'

import { $tokenUsage, compactTokens, refreshTokenUsage, type TokenBucket } from './token-usage-store'

/** Token monitor (v1.4.7): live context fill plus input / cache / output / total
 *  for this session, today and lifetime, per model. Numbers come from the core's
 *  own counter (`GET /api/usage`), the same tracker the phone and the Pamerkan
 *  card read, so all three always agree. Counts only, nothing private. */
export function TokenMonitor({ sessionId, usage }: { sessionId?: null | string; usage?: UsageStats }) {
  const summary = useStore($tokenUsage)

  useEffect(() => {
    void refreshTokenUsage(sessionId ?? null)
  }, [sessionId])

  const max = usage?.context_max ?? 0
  const used = usage?.context_used ?? 0
  const pct = Math.max(0, Math.min(100, Math.round(usage?.context_percent ?? (max ? (100 * used) / max : 0))))

  return (
    <div className="flex flex-col gap-2 text-[0.6875rem]" data-slot="token-monitor">
      <div className="flex items-baseline justify-between gap-2">
        <p className="font-medium text-foreground">Pemakaian token</p>
        {max > 0 && (
          <span className="tabular-nums text-muted-foreground" data-testid="token-monitor-context">
            konteks {pct}% · {compactTokens(used)}/{compactTokens(max)}
          </span>
        )}
      </div>

      {!summary && <p className="text-muted-foreground">Belum ada data dari core (Neovarch ≥ 1.4.7).</p>}

      {summary && (
        <>
          {summary.session && <BucketRow bucket={summary.session} label="Sesi ini" />}
          <BucketRow bucket={summary.today} label="Hari ini" />
          <BucketRow
            bucket={summary.lifetime}
            label="Sepanjang waktu"
            note={summary.since ? `sejak ${summary.since}` : undefined}
          />

          {summary.models.length > 0 && (
            <div className="flex flex-col gap-1 pt-1">
              <p className="text-[0.625rem] uppercase tracking-wide text-muted-foreground">Per model</p>
              {summary.models.slice(0, 5).map(m => (
                <div className="flex items-center justify-between gap-2" key={m.model}>
                  <span className="truncate text-muted-foreground" title={m.provider ? `${m.model} · ${m.provider}` : m.model}>
                    {m.model}
                  </span>
                  <span className="shrink-0 tabular-nums text-foreground">{compactTokens(m.total)}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function BucketRow({ bucket, label, note }: { bucket: TokenBucket; label: string; note?: string }) {
  return (
    <div className="flex flex-col gap-0.5" data-testid={`token-row-${label}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-muted-foreground">
          {label}
          {note && <span className="ml-1 text-[0.625rem]">· {note}</span>}
        </span>
        <span className="tabular-nums font-medium text-foreground">{compactTokens(bucket.total)}</span>
      </div>
      <span className="tabular-nums text-[0.625rem] text-muted-foreground">
        masuk {compactTokens(bucket.input)}
        {bucket.cached > 0 && ` (cache ${compactTokens(bucket.cached)})`} · keluar {compactTokens(bucket.output)}
      </span>
    </div>
  )
}
