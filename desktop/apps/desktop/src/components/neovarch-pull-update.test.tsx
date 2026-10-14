import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.fn();

vi.mock("@/api/client", () => ({
  hermesApi: (req: { body?: unknown; method?: string; path: string }) =>
    api(req),
}));

import { en } from "@/i18n/en";
import { NEOVARCH_ID } from "@/i18n/neovarch-id";
import {
  nvPullAr,
  nvPullDe,
  nvPullEn,
  nvPullEs,
  nvPullFr,
  nvPullId,
  nvPullJa,
  nvPullRu,
  nvPullZh,
  nvPullZhHant,
} from "@/i18n/nv-pull";
import {
  $nvUpdateApply,
  $nvUpdateStatus,
  NEOVARCH_APPLY_IDLE,
} from "@/store/neovarch-update";

import {
  errorText,
  NeovarchPullUpdate,
  PULL_IDLE,
  type PullJob,
  viewForJob,
} from "./neovarch-pull-update";

const p = en.nvPull;

const GIT_INSTALL = {
  kind: "git",
  branch: "main",
  head: "aaaaaaaaaaaa",
  dirty: [],
};

function job(overrides: Partial<PullJob> = {}): PullJob {
  return {
    state: "running",
    steps: { detect: { status: "done", detail: "/repo" } },
    lines: [],
    ...overrides,
  };
}

describe("NeovarchPullUpdate (Perbarui)", () => {
  let bridge: Record<string, ReturnType<typeof vi.fn>>;

  beforeEach(() => {
    api.mockReset();
    $nvUpdateStatus.set(null);
    $nvUpdateApply.set(NEOVARCH_APPLY_IDLE);
    bridge = {
      check: vi.fn(),
      apply: vi
        .fn()
        .mockResolvedValue({
          ok: true,
          action: "install-script",
          started: true,
        }),
      openReleasePage: vi.fn().mockResolvedValue(undefined),
      relaunch: vi.fn().mockResolvedValue(undefined),
      onProgress: vi.fn(() => () => undefined),
    };
    (window as unknown as { neovarchUpdate: unknown }).neovarchUpdate = bridge;
  });

  afterEach(() => {
    cleanup();
    delete (window as unknown as { neovarchUpdate?: unknown }).neovarchUpdate;
  });

  it("git install: pulls, shows steps and log, then offers a restart", async () => {
    let polls = 0;
    api.mockImplementation(
      async (req: {
        method?: string;
        path: string;
        body?: { restart?: boolean };
      }) => {
        if (req.method === "POST") {
          expect(req.body).toEqual({ restart: false });

          return {
            job: job({
              steps: {
                detect: { status: "done" },
                fetch: { status: "running" },
              },
            }),
          };
        }

        if (polls++ === 0) {
          return { install: GIT_INSTALL, job: null };
        }

        return {
          install: GIT_INSTALL,
          job: job({
            state: "done",
            lines: ["bbbbbbb fix: something"],
            steps: {
              detect: { status: "done" },
              clean: { status: "done" },
              fetch: { status: "done" },
              pull: { status: "done", detail: "aaaaaaa → bbbbbbb" },
              deps: { status: "done", detail: "python" },
              extras: { status: "done", detail: "Obsidian: present" },
              restart: { status: "skipped" },
            },
            result: {
              kind: "git",
              updated: true,
              old: "a".repeat(40),
              new: "b".repeat(40),
            },
          }),
        };
      },
    );

    render(<NeovarchPullUpdate />);
    expect(screen.getByText(p.description)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: p.button }));

    await waitFor(
      () =>
        expect(
          screen.getByText(
            p.updated.replace("{old}", "aaaaaaa").replace("{new}", "bbbbbbb"),
          ),
        ).toBeTruthy(),
      {
        timeout: 3000,
      },
    );
    expect(screen.getByText("Git install: main @ aaaaaaa")).toBeTruthy();
    expect(screen.getByText(p.steps.deps)).toBeTruthy();
    expect(screen.getByText(p.steps.extras)).toBeTruthy();
    expect(screen.getByText("bbbbbbb fix: something")).toBeTruthy();
    expect(api.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: p.restartNow }));
    expect(bridge.relaunch).toHaveBeenCalledTimes(1);
  });

  it("git install with local changes: shows the dirty error and a retry", async () => {
    api.mockImplementation(async (req: { method?: string }) =>
      req.method === "POST"
        ? {
            job: job({
              state: "failed",
              code: "dirty",
              error: "Ada perubahan lokal (core/x.py)",
              steps: {
                detect: { status: "done" },
                clean: { status: "failed" },
              },
            }),
          }
        : { install: { ...GIT_INSTALL, dirty: ["core/x.py"] }, job: null },
    );
    render(<NeovarchPullUpdate />);
    fireEvent.click(screen.getByRole("button", { name: p.button }));
    await waitFor(() =>
      expect(screen.getByTestId("neovarch-pull-error").textContent).toBe(
        p.errors.dirty,
      ),
    );
    expect(screen.getByText("Ada perubahan lokal (core/x.py)")).toBeTruthy();
    expect(screen.getByTestId("neovarch-pull-update").dataset.stage).toBe(
      "error",
    );
    expect(screen.getByRole("button", { name: p.retry })).toBeTruthy();
  });

  it("deps failure says the repo was rolled back", async () => {
    api.mockImplementation(async (req: { method?: string }) =>
      req.method === "POST"
        ? {
            job: job({
              state: "failed",
              code: "deps_failed",
              error: "pip exploded",
              rolled_back: true,
            }),
          }
        : { install: GIT_INSTALL, job: null },
    );
    render(<NeovarchPullUpdate />);
    fireEvent.click(screen.getByRole("button", { name: p.button }));
    await waitFor(() =>
      expect(screen.getByTestId("neovarch-pull-error").textContent).toBe(
        `${p.errors.deps_failed} ${p.rolledBack}`,
      ),
    );
  });

  it("a second click while the core is busy reports busy", async () => {
    api.mockImplementation(async (req: { method?: string }) => {
      if (req.method === "POST") {
        throw Object.assign(new Error("HTTP 409"), { status: 409 });
      }

      return { install: GIT_INSTALL, job: null };
    });
    render(<NeovarchPullUpdate />);
    fireEvent.click(screen.getByRole("button", { name: p.button }));
    await waitFor(() =>
      expect(screen.getByTestId("neovarch-pull-error").textContent).toBe(
        p.errors.busy,
      ),
    );
  });

  it("not a git install: falls back to the GitHub Releases updater (PR #38)", async () => {
    api.mockResolvedValue({ install: { kind: "installer" }, job: null });
    bridge.check.mockResolvedValue({
      ok: true,
      currentVersion: "1.4.7",
      latestVersion: "v1.4.8",
      updateAvailable: true,
      releaseUrl:
        "https://github.com/Maftuuh1922/neovrach_Agent/releases/tag/v1.4.8",
      installKind: "installer",
      action: "install-script",
    });
    render(<NeovarchPullUpdate />);
    fireEvent.click(screen.getByRole("button", { name: p.button }));
    await waitFor(() => expect(bridge.apply).toHaveBeenCalledTimes(1));
    expect(api.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
    expect(screen.getByTestId("neovarch-pull-update").dataset.stage).toBe(
      "release",
    );

    act(() => $nvUpdateApply.set({ ...NEOVARCH_APPLY_IDLE, stage: "done" }));
    fireEvent.click(screen.getByRole("button", { name: p.restartNow }));
    expect(bridge.relaunch).toHaveBeenCalled();
  });

  it("release fallback on an AppImage/deb points to the release page", async () => {
    api.mockRejectedValue(new Error("404")); // an older core without the endpoint
    bridge.check.mockResolvedValue({
      ok: true,
      currentVersion: "1.4.7",
      latestVersion: "v1.4.8",
      updateAvailable: true,
      releaseUrl:
        "https://github.com/Maftuuh1922/neovrach_Agent/releases/tag/v1.4.8",
      installKind: "deb",
      action: "release-page",
    });
    render(<NeovarchPullUpdate />);
    fireEvent.click(screen.getByRole("button", { name: p.button }));
    await waitFor(() => expect(screen.getByText(p.releaseManual)).toBeTruthy());
    expect(bridge.apply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: p.openRelease }));
    expect(bridge.openReleasePage).toHaveBeenCalledWith(
      "https://github.com/Maftuuh1922/neovrach_Agent/releases/tag/v1.4.8",
    );
  });

  it("release fallback already up to date", async () => {
    api.mockResolvedValue({ install: { kind: "package" }, job: null });
    bridge.check.mockResolvedValue({
      ok: true,
      currentVersion: "1.4.8",
      latestVersion: "v1.4.8",
      updateAvailable: false,
      releaseUrl: "x",
      installKind: "installer",
      action: "install-script",
    });
    render(<NeovarchPullUpdate />);
    fireEvent.click(screen.getByRole("button", { name: p.button }));
    await waitFor(() => expect(screen.getByText(p.upToDate)).toBeTruthy());
  });
});

describe("pull update helpers and strings", () => {
  it("maps jobs to card stages", () => {
    expect(viewForJob(PULL_IDLE, job()).stage).toBe("running");
    expect(
      viewForJob(
        PULL_IDLE,
        job({ state: "done", result: { updated: false, up_to_date: true } }),
      ).stage,
    ).toBe("uptodate");
    expect(
      viewForJob(PULL_IDLE, job({ state: "done", result: { updated: true } }))
        .stage,
    ).toBe("updated");

    const failed = viewForJob(
      PULL_IDLE,
      job({ state: "failed", code: "diverged", error: "x" }),
    );

    expect([failed.stage, failed.code, failed.message]).toEqual([
      "error",
      "diverged",
      "x",
    ]);
    expect(viewForJob(PULL_IDLE, job({ state: "failed" })).code).toBe(
      "internal",
    );
    expect(errorText(p, "nope")).toBe(p.errors.internal);
  });

  it('every locale has every string, and the Indonesian base shows "Perbarui"', () => {
    const shape = (o: object): string[] =>
      Object.entries(o)
        .flatMap(([k, v]) =>
          v && typeof v === "object" ? shape(v).map((s) => `${k}.${s}`) : [k],
        )
        .sort();

    const keys = shape(nvPullEn);

    for (const block of [
      nvPullId,
      nvPullDe,
      nvPullEs,
      nvPullFr,
      nvPullJa,
      nvPullRu,
      nvPullAr,
      nvPullZh,
      nvPullZhHant,
    ]) {
      expect(shape(block)).toEqual(keys);
      expect(
        Object.values(block).every((v) =>
          typeof v === "string" ? v.trim().length > 0 : true,
        ),
      ).toBe(true);
    }

    expect(
      (NEOVARCH_ID as unknown as { nvPull: { button: string } }).nvPull.button,
    ).toBe("Perbarui");
  });
});
