"use client";

import * as React from "react";
import { AlertTriangle, Ban, CheckCircle2, CircleDashed, Loader2, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorState, EmptyState, StatusPill } from "@/components/ui/states";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { cn, formatDuration } from "@/lib/utils";
import type { StageProgress } from "@/lib/types";

const STAGE_STATUS_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  done: CheckCircle2,
  running: Loader2,
  failed: AlertTriangle,
  skipped: CircleDashed,
  pending: CircleDashed,
};

function StageList({ stages }: { stages: StageProgress[] }) {
  return (
    <ol className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
      {stages.map((stage) => {
        const Icon = STAGE_STATUS_ICON[stage.status] ?? CircleDashed;
        return (
          <li
            key={stage.id}
            className={cn(
              "flex items-start gap-2.5 rounded-lg border px-3 py-2.5 transition-colors",
              stage.status === "running"
                ? "border-primary/40 bg-primary/5"
                : stage.status === "done"
                  ? "border-border bg-surface-muted/40"
                  : stage.status === "failed"
                    ? "border-destructive/40 bg-destructive/5"
                    : "border-border/60 bg-transparent",
            )}
          >
            <Icon
              className={cn(
                "mt-0.5 size-3.5 shrink-0",
                stage.status === "running" && "animate-spin text-primary",
                stage.status === "done" && "text-emerald-400",
                stage.status === "failed" && "text-destructive",
                (stage.status === "pending" || stage.status === "skipped") && "text-muted-foreground/50",
              )}
            />
            <div className="min-w-0">
              <p className="text-xs font-medium">{stage.label}</p>
              <p className="truncate text-2xs text-muted-foreground" title={stage.detail ?? undefined}>
                {stage.detail || (stage.status === "pending" ? "waiting" : stage.status)}
                {stage.elapsed_ms ? ` · ${formatDuration(stage.elapsed_ms)}` : ""}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Renders children only when there is a completed analysis to show; otherwise it
 * explains exactly what is happening (idle, running, failed, cancelled).
 */
export function RunGate({ children, title = "Select or start an analysis" }: { children: React.ReactNode; title?: string }) {
  const { analysis, activeRun, error, expired, complete, loading, startAnalysis, starting } = useAnalysisContext();
  const [url, setUrl] = React.useState("");

  if (loading && !analysis) {
    return (
      <div className="flex h-[60vh] items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" /> Loading analysis state…
      </div>
    );
  }

  if (error && !analysis) {
    return <ErrorState error={error} title="Could not load analyses" className="m-6" />;
  }

  if (!analysis) {
    return (
      <EmptyState
        icon={Terminal}
        title={title}
        detail={expired
          ? "Your previous analysis expired after inactivity or the API restarted. The temporary results are no longer available; paste the repository URL again to create a fresh analysis."
          : "Paste a GitHub repository URL you can access in the bar above and press “Analyze Repository”. RepoLens fetches the source via the GitHub API, parses it statically, and stores temporary analysis results for this session."}
        className="min-h-[50vh]"
        action={
          <form
            className="mt-3 flex w-full max-w-xl items-center gap-2"
            onSubmit={async (event) => {
              event.preventDefault();
              if (!url.trim()) return;
              await startAnalysis(url.trim());
            }}
          >
            <input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://github.com/owner/repository"
              className="h-9 flex-1 rounded-md border border-input bg-surface-muted/70 px-3 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
            <Button type="submit" loading={starting}>
              Analyze Repository
            </Button>
          </form>
        }
      />
    );
  }

  if (activeRun) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-10">
        <div className="panel p-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <Loader2 className="size-4 animate-spin text-primary" />
                <h2 className="text-sm font-semibold">Analysing repository</h2>
                <StatusPill status={activeRun.status} />
              </div>
              <p className="mt-1.5 text-xs text-muted-foreground">{activeRun.message || "Fetching repository metadata from GitHub…"}</p>
            </div>
            <div className="text-right">
              <p className="kpi-value">{Math.round((activeRun.progress ?? 0) * 100)}%</p>
              <p className="kpi-label">progress</p>
            </div>
          </div>

          <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-secondary">
            <div className="h-full rounded-full bg-gradient-to-r from-primary to-accent transition-all duration-700" style={{ width: `${Math.round((activeRun.progress ?? 0) * 100)}%` }} />
          </div>

          <div className="mt-6">
            <StageList stages={activeRun.stages} />
          </div>

          {activeRun.warnings.length ? (
            <div className="mt-5 rounded-lg border border-amber-500/25 bg-amber-500/5 p-3">
              <p className="text-xs font-medium text-amber-200">Warnings so far</p>
              <ul className="mt-1.5 space-y-1">
                {activeRun.warnings.slice(0, 6).map((warning, index) => (
                  <li key={index} className="text-2xs text-amber-100/80">
                    {warning.message}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  if (analysis.status === "failed") {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10">
        <div className="panel p-6">
          <div className="flex items-center gap-2">
            <AlertTriangle className="size-4 text-destructive" />
            <h2 className="text-sm font-semibold">Analysis failed</h2>
            <StatusPill status="failed" />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            {analysis.error?.message ?? "The run stopped before producing artefacts."}
          </p>
          {analysis.error?.hint ? <p className="mt-1.5 text-xs text-muted-foreground/90">{analysis.error.hint}</p> : null}
          {analysis.error ? (
            <pre className="mono mt-3 max-h-48 overflow-auto rounded-lg border border-border bg-surface-muted p-3 text-2xs text-muted-foreground">
              {JSON.stringify(analysis.error.detail ?? { code: analysis.error.code }, null, 2)}
            </pre>
          ) : null}
          <div className="mt-4">
            <StageList stages={analysis.stages} />
          </div>
        </div>
      </div>
    );
  }

  if (analysis.status === "cancelled") {
    return (
      <EmptyState
        icon={Ban}
        title="This analysis was cancelled"
        detail="Start a new run from the bar above to collect artefacts for this repository."
        className="min-h-[50vh]"
      />
    );
  }

  if (!complete) return null;

  return <>{children}</>;
}
