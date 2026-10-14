import { useStore } from "@nanostores/react";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { hermesApi } from "@/api/client";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n";
import type { NvPullTranslations } from "@/i18n/nv-pull";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Loader2,
  RefreshCw,
} from "@/lib/icons";
import { cn } from "@/lib/utils";
import {
  $nvUpdateApply,
  $nvUpdateStatus,
  applyNeovarchUpdate,
  checkNeovarchUpdate,
  openNeovarchReleasePage,
  relaunchNeovarch,
} from "@/store/neovarch-update";

/**
 * Settings ▸ Tentang ▸ "Perbarui": `neovarch update` from the desktop.
 *
 * Git install (the core runs from a clone of the repo): the core's
 * POST /api/update/pull refuses a dirty tree, fetches, fast-forwards,
 * reinstalls dependencies (rolling back to the previous commit when that
 * fails) and runs the optional extras check; this card polls the job and
 * then offers to restart the app (which restarts the core with it).
 *
 * Anything else: the GitHub Releases updater from PR #38 (store/neovarch-update)
 * checks and installs the latest release; its progress is shared with
 * NeovarchUpdateCard. The new core runs the extras check on its first start.
 */

export const PULL_PATH = "/api/update/pull";
export const PULL_POLL_MS = 700;

export type PullStepStatus =
  "done" | "failed" | "manual" | "running" | "skipped" | "warning";

export interface PullJob {
  state: "done" | "failed" | "running";
  step?: string;
  steps: Record<string, { detail?: string; status: PullStepStatus }>;
  lines: string[];
  result?: null | {
    kind?: string;
    new?: string;
    old?: string;
    up_to_date?: boolean;
    updated?: boolean;
  };
  error?: null | string;
  code?: null | string;
  rolled_back?: boolean;
}

export interface PullInstall {
  kind: "git" | "installer" | "installer-windows" | "package";
  branch?: string;
  head?: string;
  dirty?: string[];
}

export type PullStage =
  | "idle"
  | "detecting"
  | "running"
  | "updated"
  | "uptodate"
  | "error"
  | "release";

export interface PullView {
  stage: PullStage;
  install: PullInstall | null;
  job: PullJob | null;
  code: null | string;
  message: null | string;
}

export const PULL_IDLE: PullView = {
  stage: "idle",
  install: null,
  job: null,
  code: null,
  message: null,
};

const GIT_STEPS = [
  "detect",
  "clean",
  "fetch",
  "pull",
  "deps",
  "extras",
  "restart",
] as const;

const fill = (template: string, values: Record<string, string>): string =>
  Object.entries(values).reduce(
    (text, [key, value]) => text.replace(`{${key}}`, value),
    template,
  );

/** Pure: what a finished or running job means for the card (exported for tests). */
export function viewForJob(view: PullView, job: PullJob): PullView {
  if (job.state === "running") {
    return { ...view, stage: "running", job };
  }

  if (job.state === "failed") {
    return {
      ...view,
      stage: "error",
      job,
      code: job.code ?? "internal",
      message: job.error ?? null,
    };
  }

  return { ...view, stage: job.result?.updated ? "updated" : "uptodate", job };
}

export function errorText(p: NvPullTranslations, code: null | string): string {
  return (
    (code && (p.errors as Record<string, string>)[code]) || p.errors.internal
  );
}

function statusFromError(error: unknown): number | undefined {
  const status = (error as { status?: unknown })?.status;

  if (typeof status === "number") {
    return status;
  }

  return /\b409\b/.test(String(error)) ? 409 : undefined;
}

export function usePullUpdate(pollMs = PULL_POLL_MS) {
  const [view, setView] = useState<PullView>(PULL_IDLE);
  const timer = useRef<null | ReturnType<typeof setTimeout>>(null);
  const alive = useRef(true);

  useEffect(
    () => () => {
      alive.current = false;

      if (timer.current) {
        clearTimeout(timer.current);
      }
    },
    [],
  );

  const poll = useCallback(
    async (base: PullView): Promise<void> => {
      try {
        const res = await hermesApi<{ job: null | PullJob }>({
          path: PULL_PATH,
        });

        if (!alive.current || !res.job) {
          return;
        }

        const next = viewForJob(base, res.job);
        setView(next);

        if (next.stage === "running") {
          timer.current = setTimeout(() => void poll(next), pollMs);
        }
      } catch {
        // The core restarts or blips: keep polling a little, the job survives in memory.
        if (alive.current) {
          timer.current = setTimeout(() => void poll(base), pollMs * 2);
        }
      }
    },
    [pollMs],
  );

  const start = useCallback(async (): Promise<void> => {
    setView({ ...PULL_IDLE, stage: "detecting" });
    let install: null | PullInstall = null;

    try {
      const res = await hermesApi<{
        install: PullInstall;
        job: null | PullJob;
      }>({ path: PULL_PATH });

      install = res.install ?? null;
    } catch {
      install = null; // an older core without /api/update/pull: use the release updater
    }

    if (!alive.current) {
      return;
    }

    if (install?.kind !== "git") {
      // Not a git install: the GitHub Releases updater (PR #38) does the work.
      const base: PullView = { ...PULL_IDLE, stage: "release", install };
      setView(base);
      const status = await checkNeovarchUpdate();

      if (!alive.current) {
        return;
      }

      if (!status?.ok) {
        setView({
          ...base,
          stage: "error",
          code: "release_failed",
          message: status?.error ?? null,
        });
      } else if (!status.updateAvailable) {
        setView({ ...base, stage: "uptodate" });
      } else if (status.action !== "release-page") {
        await applyNeovarchUpdate();
      }

      return;
    }

    const base: PullView = { ...PULL_IDLE, stage: "running", install };
    setView(base);

    try {
      const res = await hermesApi<{ job: PullJob }>({
        path: PULL_PATH,
        method: "POST",
        body: { restart: false },
      });

      if (!alive.current) {
        return;
      }

      const next = viewForJob(base, res.job);
      setView(next);

      if (next.stage === "running") {
        timer.current = setTimeout(() => void poll(next), pollMs);
      }
    } catch (error) {
      if (alive.current) {
        setView({
          ...base,
          stage: "error",
          code: statusFromError(error) === 409 ? "busy" : "unreachable",
          message: error instanceof Error ? error.message : String(error),
        });
      }
    }
  }, [poll, pollMs]);

  const reset = useCallback(() => setView(PULL_IDLE), []);

  return { view, start, reset };
}

const STEP_MARK: Record<PullStepStatus, string> = {
  done: "✓",
  failed: "✗",
  manual: "→",
  running: "…",
  skipped: "–",
  warning: "!",
};

export function NeovarchPullUpdate(): ReactElement {
  const { t } = useI18n();
  const p = t.nvPull;
  const { view, start, reset } = usePullUpdate();
  const releaseApply = useStore($nvUpdateApply);
  const releaseStatus = useStore($nvUpdateStatus);
  const logRef = useRef<HTMLPreElement | null>(null);
  const lines = view.job?.lines ?? [];

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [lines.length]);

  const releaseBusy =
    view.stage === "release" &&
    (releaseApply.stage === "running" || releaseApply.stage === "downloading");

  const busy =
    view.stage === "detecting" || view.stage === "running" || releaseBusy;

  const releaseManual =
    view.stage === "release" &&
    releaseStatus?.updateAvailable &&
    releaseStatus.action === "release-page";

  const headline =
    view.stage === "detecting"
      ? p.detecting
      : view.stage === "running"
        ? p.running
        : view.stage === "updated"
          ? fill(p.updated, {
              old: (view.job?.result?.old ?? "").slice(0, 7),
              new: (view.job?.result?.new ?? "").slice(0, 7),
            })
          : view.stage === "uptodate"
            ? p.upToDate
            : view.stage === "error"
              ? p.failed
              : view.stage === "release"
                ? releaseApply.stage === "error"
                  ? p.failed
                  : releaseApply.stage === "done"
                    ? t.nvUpdate.installedRestart
                    : releaseBusy
                      ? p.running
                      : p.releaseInstall
                : p.title;

  const tone =
    view.stage === "error" || releaseApply.stage === "error"
      ? "error"
      : view.stage === "updated"
        ? "ok"
        : "idle";

  const showRestart =
    view.stage === "updated" ||
    (view.stage === "release" && releaseApply.stage === "done");

  return (
    <div
      className={cn(
        "rounded-xl border px-4 py-3 text-sm",
        tone === "error" && "border-destructive/35 bg-destructive/5",
        tone === "ok" && "border-primary/30 bg-primary/5",
        tone === "idle" && "border-border/70 bg-muted/20",
      )}
      data-stage={view.stage}
      data-testid="neovarch-pull-update"
    >
      <div className="flex items-start gap-2">
        {busy ? (
          <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-muted-foreground" />
        ) : tone === "error" ? (
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
        ) : view.stage === "updated" || view.stage === "uptodate" ? (
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
        ) : null}
        <div className="min-w-0 flex-1">
          <p className="font-medium">{headline}</p>
          {view.stage === "idle" && (
            <p className="mt-1 text-xs text-muted-foreground">
              {p.description}
            </p>
          )}
          {view.install?.kind === "git" && (
            <p className="mt-1 text-xs text-muted-foreground">
              {fill(p.gitInstall, {
                branch: view.install.branch ?? "?",
                head: (view.install.head ?? "").slice(0, 7),
              })}
            </p>
          )}
          {view.stage === "error" && (
            <p
              className="mt-1 text-xs text-muted-foreground"
              data-testid="neovarch-pull-error"
            >
              {errorText(p, view.code)}
              {view.job?.rolled_back ? ` ${p.rolledBack}` : ""}
            </p>
          )}
          {view.stage === "error" && view.message && (
            <p className="mt-1 break-words font-mono text-[11px] text-muted-foreground">
              {view.message}
            </p>
          )}
          {view.stage === "release" &&
            releaseApply.stage === "error" &&
            releaseApply.message && (
              <p className="mt-1 text-xs text-muted-foreground">
                {releaseApply.message}
              </p>
            )}
          {releaseManual && (
            <p className="mt-1 text-xs text-muted-foreground">
              {p.releaseManual}
            </p>
          )}
        </div>
      </div>

      {view.job && Object.keys(view.job.steps).length > 0 && (
        <ul
          className="mt-3 grid gap-1 text-xs"
          data-testid="neovarch-pull-steps"
        >
          {GIT_STEPS.filter((id) => view.job?.steps[id]).map((id) => {
            const step = view.job!.steps[id];

            return (
              <li
                className={cn(
                  "flex gap-2",
                  step.status === "failed" && "text-destructive",
                  step.status === "skipped" && "text-muted-foreground",
                )}
                data-status={step.status}
                key={id}
              >
                <span aria-hidden className="w-3 text-center">
                  {STEP_MARK[step.status] ?? "·"}
                </span>
                <span className="font-medium">{p.steps[id]}</span>
                {step.detail && (
                  <span className="min-w-0 truncate text-muted-foreground">
                    {step.detail}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {lines.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            {p.log}
          </p>
          <pre
            className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg bg-background/70 px-3 py-2 font-mono text-[11px] leading-relaxed"
            ref={logRef}
          >
            {lines.join("\n")}
          </pre>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        {showRestart ? (
          <>
            <Button onClick={() => relaunchNeovarch()} size="sm">
              <RefreshCw className="size-3" />
              {p.restartNow}
            </Button>
            <Button onClick={reset} size="sm" variant="textStrong">
              {p.later}
            </Button>
          </>
        ) : (
          <Button disabled={busy} onClick={() => void start()} size="sm">
            {busy ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <RefreshCw className="size-3" />
            )}
            {view.stage === "error" ? p.retry : p.button}
          </Button>
        )}
        {releaseManual && (
          <Button
            onClick={() => openNeovarchReleasePage(releaseStatus?.releaseUrl)}
            size="sm"
            variant="text"
          >
            <ExternalLink className="size-3" />
            {p.openRelease}
          </Button>
        )}
      </div>
    </div>
  );
}
