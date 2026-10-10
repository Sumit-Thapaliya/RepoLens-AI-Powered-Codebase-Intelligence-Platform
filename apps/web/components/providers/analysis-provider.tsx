"use client";

import * as React from "react";
import { useSWRConfig } from "swr";
import {
  ApiError,
  cancelAnalysis as cancelRun,
  createAnalysis,
  getAnalysis,
  heartbeatAnalysis,
  listAnalyses,
  releaseAnalysis,
} from "@/lib/api";
import type { Analysis, RepoMetadata } from "@/lib/types";
import { useToast } from "@/components/ui/states";
import { useCapabilities } from "@/lib/hooks";
import { getWindowId, readCurrentRun, readWindowRuns, writeCurrentRun, writeWindowRuns } from "@/lib/window";

/** How often an active, visible tab refreshes its inactivity lease. */
const HEARTBEAT_MS = 20_000;

type RunSummary = Analysis & { repo?: { id: string; full_name?: string; url?: string } };

export interface AnalysisContextValue {
  /** Runs owned by this window only. */
  analyses: RunSummary[];
  analysis: Analysis | null;
  analysisId: string | null;
  repo: RepoMetadata | null;
  complete: boolean;
  loading: boolean;
  starting: boolean;
  error: ApiError | null;
  /** True when a previously selected run disappeared after expiry or an API restart. */
  expired: boolean;
  /** Only set while a run is executing (drives the progress panel). */
  activeRun: Analysis | null;
  selectAnalysis: (analysisId: string) => void;
  startAnalysis: (url: string, branch?: string | null) => Promise<string | null>;
  cancel: () => Promise<void>;
  remove: (analysisId: string) => Promise<void>;
  refreshList: () => Promise<void>;
}

const AnalysisContext = React.createContext<AnalysisContextValue | null>(null);

export function useAnalysisContext(): AnalysisContextValue {
  const context = React.useContext(AnalysisContext);
  if (!context) throw new Error("useAnalysisContext must be used inside <AnalysisProvider>");
  return context;
}

export function AnalysisProvider({ children }: { children: React.ReactNode }) {
  const { push } = useToast();
  const { data: runtimeCapabilities } = useCapabilities();
  const { mutate: mutateSWR } = useSWRConfig();
  const clearSWRAnalysisCache = React.useCallback((id: string) => {
    void mutateSWR(
      (key) => typeof key === "string" && key.includes(id),
      undefined,
      { revalidate: false },
    );
  }, [mutateSWR]);
  const [analyses, setAnalyses] = React.useState<RunSummary[]>([]);
  const [analysisId, setAnalysisId] = React.useState<string | null>(null);
  const [analysis, setAnalysis] = React.useState<Analysis | null>(null);
  const [repo, setRepo] = React.useState<RepoMetadata | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [starting, setStarting] = React.useState(false);
  const [error, setError] = React.useState<ApiError | null>(null);
  const [expired, setExpired] = React.useState(false);

  /** Sets the shown analysis and remembers it for this window only. */
  const commitCurrent = React.useCallback((id: string | null) => {
    setAnalysisId(id);
    writeCurrentRun(id);
  }, []);

  /** Loads this window's runs. Runs the server no longer has are forgotten by this window. */
  const fetchRuns = React.useCallback(async (): Promise<RunSummary[]> => {
    const ids = readWindowRuns();
    if (ids.length === 0) {
      setAnalyses([]);
      return [];
    }
    try {
      const payload = await listAnalyses(ids);
      setError(null);
      const found = payload.analyses;
      const foundIds = new Set(found.map((run) => run.id));
      const kept = ids.filter((id) => foundIds.has(id));
      const expiredIds = ids.filter((id) => !foundIds.has(id));
      const hadExpiredRun = expiredIds.length > 0;
      if (hadExpiredRun) {
        writeWindowRuns(kept);
        expiredIds.forEach(clearSWRAnalysisCache);
      }
      if (hadExpiredRun) setExpired(true);
      setAnalyses(found);
      return found;
    } catch (cause) {
      if (cause instanceof ApiError) setError(cause);
      return [];
    }
  }, [clearSWRAnalysisCache]);

  const refreshList = React.useCallback(async () => {
    await fetchRuns();
  }, [fetchRuns]);

  /* Bootstrap: restore this window's last run. A new window starts empty. */
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      const runs = await fetchRuns();
      if (cancelled) return;
      const stored = readCurrentRun();
      if (runs.length === 0 && stored && readWindowRuns().includes(stored)) {
        // The list request failed (for example the API is restarting). Keep the window's analysis.
        setAnalysisId(stored);
      } else {
        const candidate = (stored && runs.find((run) => run.id === stored)) || runs[0];
        commitCurrent(candidate ? candidate.id : null);
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchRuns, commitCurrent]);

  /* The lease follows human activity, not merely an open browser tab. */
  const inactivityWindowMs = (runtimeCapabilities?.limits.window_ttl_seconds ?? 1800) * 1000;
  const heartbeatIntervalMs = Math.max(250, Math.min(HEARTBEAT_MS, inactivityWindowMs / 3));
  const recentActivityMs = Math.min(inactivityWindowMs, heartbeatIntervalMs + 1000);
  React.useEffect(() => {
    let cancelled = false;
    let requestInFlight = false;
    let lastActivityAt = Date.now();
    let lastPingAt = 0;

    const expireIfOverdue = (now: number) => {
      if (now - lastActivityAt < inactivityWindowMs + recentActivityMs) return false;
      const ids = readWindowRuns();
      if (ids.length === 0) return false;
      setExpired(true);
      setError(null);
      setAnalyses([]);
      setAnalysis(null);
      setRepo(null);
      writeWindowRuns([]);
      ids.forEach(clearSWRAnalysisCache);
      if (ids.includes(readCurrentRun() ?? "")) commitCurrent(null);
      return true;
    };

    const ping = async (force = false) => {
      const now = Date.now();
      if (cancelled || requestInFlight || expireIfOverdue(now)) return;
      if (
        document.visibilityState !== "visible" ||
        (!force && now - lastActivityAt >= recentActivityMs)
      ) return;
      const ids = readWindowRuns();
      if (ids.length === 0) return;
      requestInFlight = true;
      lastPingAt = now;
      try {
        const windowId = getWindowId();
        const results = await Promise.all(
          ids.map(async (id) => {
            try {
              await heartbeatAnalysis(id, windowId);
              return { id, gone: false };
            } catch (cause) {
              return { id, gone: cause instanceof ApiError && cause.status === 404 };
            }
          }),
        );
        const gone = results.filter((result) => result.gone).map((result) => result.id);
        if (gone.length === 0 || cancelled) return;
        setExpired(true);
        writeWindowRuns(readWindowRuns().filter((id) => !gone.includes(id)));
        gone.forEach(clearSWRAnalysisCache);
        const runs = await fetchRuns();
        setAnalysisId((current) => {
          if (!current || !gone.includes(current)) return current;
          const next = runs[0]?.id ?? null;
          writeCurrentRun(next);
          return next;
        });
      } finally {
        requestInFlight = false;
      }
    };

    const noteActivity = () => {
      if (document.visibilityState === "hidden") return;
      const now = Date.now();
      if (expireIfOverdue(now)) return;
      const wasIdle = now - lastActivityAt >= recentActivityMs;
      lastActivityAt = now;
      if (wasIdle && now - lastPingAt >= heartbeatIntervalMs) void ping(true);
    };
    const onVisibilityChange = () => {
      if (document.visibilityState !== "visible") return;
      const now = Date.now();
      if (expireIfOverdue(now)) return;
      lastActivityAt = now;
      void ping(true);
    };

    const activityEvents: (keyof WindowEventMap)[] = ["pointerdown", "keydown", "mousemove", "touchstart", "wheel"];
    activityEvents.forEach((eventName) => window.addEventListener(eventName, noteActivity, { passive: true }));
    document.addEventListener("visibilitychange", onVisibilityChange);
    void ping(true);
    const timer = setInterval(() => void ping(), heartbeatIntervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
      activityEvents.forEach((eventName) => window.removeEventListener(eventName, noteActivity));
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [fetchRuns, clearSWRAnalysisCache, inactivityWindowMs, heartbeatIntervalMs, recentActivityMs, commitCurrent]);

  /* Details for the selected run, polled while it is still executing. */
  React.useEffect(() => {
    if (!analysisId) {
      setAnalysis(null);
      setRepo(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const load = async () => {
      try {
        const payload = await getAnalysis(analysisId);
        if (cancelled) return;
        setAnalysis(payload.analysis);
        setRepo(payload.repo ?? null);
        setError(null);
        if (payload.analysis.status === "queued" || payload.analysis.status === "running") {
          timer = setTimeout(load, 1500);
        } else {
          void fetchRuns();
        }
      } catch (cause) {
        if (cancelled) return;
        const apiError = cause instanceof ApiError ? cause : new ApiError(String(cause));
        setError(apiError);
        if (apiError.status === 404) {
          setExpired(true);
          setError(null);
          clearSWRAnalysisCache(analysisId);
          writeWindowRuns(readWindowRuns().filter((id) => id !== analysisId));
          setAnalyses((current) => current.filter((run) => run.id !== analysisId));
          setAnalysis(null);
          setRepo(null);
          commitCurrent(null);
          void fetchRuns().then((runs) => {
            if (!cancelled && runs[0]) commitCurrent(runs[0].id);
          });
        } else {
          timer = setTimeout(load, 4000);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [analysisId, fetchRuns, clearSWRAnalysisCache, commitCurrent]);

  /* Surface terminal state changes once. */
  const lastStatus = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!analysis) return;
    if (lastStatus.current && lastStatus.current !== analysis.status) {
      if (analysis.status === "complete") {
        push({ tone: "success", title: "Analysis complete", detail: `${analysis.file_count} files parsed for ${repo?.full_name ?? "repository"}.` });
      } else if (analysis.status === "failed") {
        push({ tone: "error", title: "Analysis failed", detail: analysis.error?.message ?? "See the run log for details." });
      }
    }
    lastStatus.current = analysis.status;
  }, [analysis, repo, push]);

  const selectAnalysis = React.useCallback(
    (id: string) => {
      if (!readWindowRuns().includes(id)) return;
      commitCurrent(id);
      setAnalysis(null);
      setExpired(false);
    },
    [commitCurrent],
  );

  const startAnalysis = React.useCallback(
    async (url: string, branch?: string | null) => {
      setStarting(true);
      setError(null);
      setExpired(false);
      const windowId = getWindowId();
      const previous = readWindowRuns();
      try {
        const result = await createAnalysis(url, branch ?? null, true, windowId);
        previous.filter((id) => id !== result.analysis_id).forEach(clearSWRAnalysisCache);
        writeWindowRuns([result.analysis_id]);
        commitCurrent(result.analysis_id);
        setAnalysis(result.analysis);
        setRepo(result.repo);
        // A new URL discards this window's earlier analysis (kept only if another open window still uses it).
        await Promise.all(
          previous
            .filter((id) => id !== result.analysis_id)
            .map((id) => releaseAnalysis(id, windowId).catch(() => undefined)),
        );
        void fetchRuns();
        push({
          tone: "info",
          title: result.reused ? "Re-using running analysis" : "Analysis queued",
          detail: `${result.repo.full_name} · fetching repository data from GitHub`,
        });
        return result.analysis_id;
      } catch (cause) {
        const apiError = cause instanceof ApiError ? cause : new ApiError(String(cause));
        setError(apiError);
        push({ tone: "error", title: "Could not start analysis", detail: apiError.message });
        return null;
      } finally {
        setStarting(false);
      }
    },
    [push, fetchRuns, commitCurrent, clearSWRAnalysisCache],
  );

  const cancel = React.useCallback(async () => {
    if (!analysisId) return;
    try {
      await cancelRun(analysisId);
      push({ tone: "info", title: "Analysis cancelled" });
    } catch (cause) {
      push({ tone: "error", title: "Cancel failed", detail: cause instanceof Error ? cause.message : String(cause) });
    }
  }, [analysisId, push]);

  const remove = React.useCallback(
    async (id: string) => {
      try {
        // Release it from this window; the server deletes it unless another open window still uses it.
        await releaseAnalysis(id, getWindowId());
        clearSWRAnalysisCache(id);
        writeWindowRuns(readWindowRuns().filter((item) => item !== id));
        push({ tone: "success", title: "Analysis removed" });
        const runs = await fetchRuns();
        if (analysisId === id) commitCurrent(runs[0]?.id ?? null);
      } catch (cause) {
        push({ tone: "error", title: "Delete failed", detail: cause instanceof Error ? cause.message : String(cause) });
      }
    },
    [analysisId, push, fetchRuns, commitCurrent, clearSWRAnalysisCache],
  );

  const value: AnalysisContextValue = {
    analyses,
    analysis,
    analysisId,
    repo,
    complete: analysis?.status === "complete",
    loading,
    starting,
    error,
    expired,
    activeRun: analysis && (analysis.status === "queued" || analysis.status === "running") ? analysis : null,
    selectAnalysis,
    startAnalysis,
    cancel,
    remove,
    refreshList,
  };

  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>;
}

export function useAnalysis() {
  return useAnalysisContext();
}

/** Convenience: the id of the run a page should query, or null. */
export function useCurrentAnalysisId(): string | null {
  const { analysisId, complete } = useAnalysisContext();
  return complete ? analysisId : null;
}
