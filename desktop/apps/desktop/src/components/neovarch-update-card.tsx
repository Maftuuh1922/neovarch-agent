import { useStore } from '@nanostores/react'
import { type ReactElement, useEffect, useRef } from 'react'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { useI18n } from '@/i18n'
import { AlertTriangle, CheckCircle2, ExternalLink, Loader2, RefreshCw } from '@/lib/icons'
import { cn } from '@/lib/utils'
import {
  $nvUpdateApply,
  $nvUpdateChecking,
  $nvUpdateStatus,
  applyNeovarchUpdate,
  checkNeovarchUpdate,
  openNeovarchReleasePage,
  relaunchNeovarch,
  resetNeovarchApply
} from '@/store/neovarch-update'

const fill = (template: string, key: string, value: string): string => template.replace(`{${key}}`, value)

/**
 * Neovarch's update card (Settings ▸ Tentang and the "Check for Updates…"
 * dialog): GitHub Releases status, release-notes excerpt, the one action that
 * fits this install, and the installer log / restart prompt while it runs.
 */
export function NeovarchUpdateCard({
  autoCheck = false,
  onLater
}: {
  /** Check on mount when nothing has been checked yet (the menu dialog). */
  autoCheck?: boolean
  onLater?: () => void
}): ReactElement {
  const { t } = useI18n()
  const n = t.nvUpdate
  const status = useStore($nvUpdateStatus)
  const checking = useStore($nvUpdateChecking)
  const apply = useStore($nvUpdateApply)
  const logRef = useRef<HTMLPreElement | null>(null)

  useEffect(() => {
    if (autoCheck && !checking && (!status || status.skipped)) {
      void checkNeovarchUpdate()
    }
    // Only on open; a re-check is the user's button.
  }, [autoCheck])

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [apply.lines.length])

  const busy = apply.stage === 'running' || apply.stage === 'downloading'
  const available = Boolean(status?.ok && status.updateAvailable)
  const failed = Boolean(status && !status.ok && !checking)
  const tone = apply.stage === 'error' || failed ? 'error' : available ? 'available' : 'idle'

  const line = checking
    ? n.checking
    : apply.stage === 'error'
      ? n.failed
      : apply.stage === 'done'
        ? n.installedRestart
        : apply.stage === 'launched'
          ? n.launched
          : apply.stage === 'running'
            ? n.installing
            : apply.stage === 'downloading'
              ? fill(n.downloading, 'percent', apply.percent === null ? '' : `${apply.percent}%`)
              : failed
                ? n.checkFailed
                : available
                  ? fill(n.available, 'version', status!.latestVersion ?? '')
                  : status?.ok
                    ? n.upToDate
                    : n.title

  const primaryLabel =
    status?.action === 'install-script' ? n.updateNow : status?.action === 'windows-setup' ? n.downloadInstall : n.openRelease

  const hint =
    available && status?.action === 'release-page'
      ? status.installKind === 'appimage' || status.installKind === 'deb'
        ? n.manualHint
        : n.unsupportedHint
      : null

  return (
    <div
      className={cn(
        'rounded-xl border px-4 py-3 text-sm',
        tone === 'available' && 'border-primary/30 bg-primary/5 text-foreground',
        tone === 'error' && 'border-destructive/35 bg-destructive/5',
        tone === 'idle' && 'border-border/70 bg-muted/20 text-foreground'
      )}
      data-testid="neovarch-update-card"
    >
      <div className="flex items-start gap-2">
        {checking || busy ? (
          <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-muted-foreground" />
        ) : tone === 'error' ? (
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
        ) : available ? (
          <Codicon className="mt-0.5 size-4 shrink-0 text-primary" name="cloud-download" size="1rem" />
        ) : status?.ok ? (
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
        ) : null}
        <div className="min-w-0 flex-1">
          <p className="font-medium">{line}</p>
          {status?.currentVersion && (
            <p className="mt-1 text-xs text-muted-foreground">{fill(n.installedVersion, 'version', status.currentVersion)}</p>
          )}
          {apply.stage === 'error' && apply.message && (
            <p className="mt-1 text-xs text-muted-foreground">
              {apply.message}
              {apply.fellBackToReleasePage ? ` ${n.fellBack}` : ''}
            </p>
          )}
          {failed && status?.error && <p className="mt-1 text-xs text-muted-foreground">{status.error}</p>}
          {hint && apply.stage === 'idle' && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
        </div>
      </div>

      {available && status?.notes && apply.stage === 'idle' && (
        <p className="mt-3 max-h-40 overflow-y-auto whitespace-pre-wrap rounded-lg bg-background/60 px-3 py-2 text-xs text-muted-foreground">
          {status.notes}
        </p>
      )}

      {apply.lines.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 text-xs font-medium text-muted-foreground">{n.log}</p>
          <pre
            className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg bg-background/70 px-3 py-2 font-mono text-[11px] leading-relaxed"
            ref={logRef}
          >
            {apply.lines.join('\n')}
          </pre>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        {apply.stage === 'done' ? (
          <>
            <Button onClick={() => relaunchNeovarch()} size="sm">
              <RefreshCw className="size-3" />
              {n.restartNow}
            </Button>
            <Button
              onClick={() => {
                resetNeovarchApply()
                onLater?.()
              }}
              size="sm"
              variant="textStrong"
            >
              {n.later}
            </Button>
          </>
        ) : (
          <>
            <Button
              disabled={checking || busy || apply.stage === 'launched'}
              onClick={() => {
                resetNeovarchApply()
                void checkNeovarchUpdate()
              }}
              size="sm"
              variant="textStrong"
            >
              {checking ? <Loader2 className="size-3 animate-spin" /> : <RefreshCw className="size-3" />}
              {n.checkNow}
            </Button>
            {available && !busy && apply.stage !== 'launched' && (
              <Button onClick={() => void applyNeovarchUpdate()} size="sm">
                {primaryLabel}
              </Button>
            )}
            {(apply.stage === 'error' || available) && status?.action !== 'release-page' && (
              <Button onClick={() => openNeovarchReleasePage(status?.releaseUrl)} size="sm" variant="text">
                <ExternalLink className="size-3" />
                {apply.stage === 'error' ? n.openRelease : n.fullNotes}
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
