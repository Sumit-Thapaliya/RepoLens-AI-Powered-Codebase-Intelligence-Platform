"use client";

import * as React from "react";
import { Activity, AlertTriangle, Gauge, Info, Search, ShieldCheck } from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { StatCard } from "@/components/common/kpi";
import { PathLink } from "@/components/common/path-link";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { ErrorState, InlineNote, SkeletonCard } from "@/components/ui/states";
import { ApiError, getQuality } from "@/lib/api";
import type { QualityIssue, QualityPayload } from "@/lib/types";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { cn, formatNumber, severityColor } from "@/lib/utils";

const KIND_LABELS: Record<string, string> = {
  high_complexity: "High complexity",
  high_coupling: "High coupling",
  large_module: "Large module",
  missing_tests: "Missing tests",
  isolated_module: "Isolated module",
  circular_dependency: "Circular dependency",
  duplicate_code: "Duplicate code",
  possible_secret: "Possible secret",
  long_function: "Long function",
  god_class: "God class",
  todo_comment: "TODO/FIXME",
};

function HealthDial({ score, label }: { score: number; label: string }) {
  const tone = score >= 85 ? "#34d399" : score >= 70 ? "#38bdf8" : score >= 50 ? "#fbbf24" : "#fb7185";
  const circumference = 2 * Math.PI * 42;
  const offset = circumference * (1 - Math.max(0, Math.min(100, score)) / 100);
  return (
    <div className="flex items-center gap-4">
      <svg width="112" height="112" viewBox="0 0 112 112" className="shrink-0">
        <circle cx="56" cy="56" r="42" fill="none" stroke="#1e2530" strokeWidth="9" />
        <circle
          cx="56"
          cy="56"
          r="42"
          fill="none"
          stroke={tone}
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform="rotate(-90 56 56)"
        />
        <text x="56" y="54" textAnchor="middle" fontSize="24" fontWeight="600" fill="#e6edf7">
          {score}
        </text>
        <text x="56" y="72" textAnchor="middle" fontSize="10" fill="#8b98ab">
          / 100
        </text>
      </svg>
      <div>
        <p className="text-sm font-semibold capitalize">{label}</p>
        <p className="mt-0.5 max-w-xs text-2xs leading-relaxed text-muted-foreground">
          Weighted from coupling, complexity, cycle count and test coverage heuristics. Not a substitute for a review —
          every finding links to the exact code that triggered it.
        </p>
      </div>
    </div>
  );
}

function IssueRow({ issue }: { issue: QualityIssue }) {
  return (
    <li className="border-b border-border/60 px-5 py-3 last:border-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("rounded border px-1.5 py-0.5 text-2xs font-medium uppercase", severityColor(issue.severity))}>
              {issue.severity}
            </span>
            <span className="text-xs font-medium">{issue.title}</span>
            {issue.heuristic ? (
              <Badge variant="outline" className="font-normal">
                heuristic
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 text-2xs leading-relaxed text-muted-foreground">{issue.detail}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {issue.files[0] ? <PathLink path={issue.files[0]} line={(issue.metric?.line as number) ?? null} compact /> : null}
          {issue.files.length > 1 ? <span className="text-2xs text-muted-foreground">+{issue.files.length - 1}</span> : null}
        </div>
      </div>
      {Object.keys(issue.metric ?? {}).length ? (
        <p className="mono mt-1.5 text-2xs text-muted-foreground">
          {Object.entries(issue.metric)
            .filter(([key]) => key !== "line")
            .map(([key, value]) => `${key}=${typeof value === "number" ? value : String(value)}`)
            .join(" · ")}
        </p>
      ) : null}
    </li>
  );
}

function QualityBody() {
  const { analysisId } = useAnalysisContext();
  const [payload, setPayload] = React.useState<QualityPayload | null>(null);
  const [error, setError] = React.useState<ApiError | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [kind, setKind] = React.useState<string | null>(null);
  const [severity, setSeverity] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");

  const load = React.useCallback(async () => {
    if (!analysisId) return;
    setLoading(true);
    setError(null);
    try {
      setPayload(await getQuality(analysisId));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause : new ApiError(String(cause)));
    } finally {
      setLoading(false);
    }
  }, [analysisId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const issues = React.useMemo(() => {
    if (!payload) return [];
    const needle = query.trim().toLowerCase();
    return payload.issues.filter((issue) => {
      if (kind && issue.kind !== kind) return false;
      if (severity && issue.severity !== severity) return false;
      if (!needle) return true;
      return issue.title.toLowerCase().includes(needle) || issue.files.some((file) => file.toLowerCase().includes(needle));
    });
  }, [payload, kind, severity, query]);

  if (loading && !payload) {
    return (
      <div className="space-y-4 p-4 lg:p-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={10} />
      </div>
    );
  }
  if (error && !payload) return <ErrorState error={error} onRetry={() => void load()} className="m-6" />;
  if (!payload) return null;

  const metrics = payload.metrics as Record<string, number | Record<string, number>>;
  const thresholds = (metrics.thresholds as Record<string, number>) ?? {};
  const bySeverity = payload.summary.by_severity;

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div>
        <h1 className="text-base font-semibold tracking-tight">Code quality</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Static heuristics over {formatNumber(Number(metrics.code_files ?? metrics.files ?? 0))} code files
          {Number(metrics.files ?? 0) > Number(metrics.code_files ?? 0)
            ? ` (of ${formatNumber(Number(metrics.files))}; documentation, data and assets are excluded)`
            : ""}
          , including {formatNumber(Number(metrics.production_files ?? 0))} production and{" "}
          {formatNumber(Number(metrics.test_files ?? 0))} test files. Each finding is traceable to source.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <section className="panel p-5">
          <HealthDial score={payload.summary.health_score} label={payload.summary.health_label} />
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(["high", "medium", "low", "info"] as const).map((level) => (
              <div key={level} className="rounded-lg border border-border bg-surface-muted/40 px-3 py-2">
                <p className="text-2xs uppercase tracking-wider text-muted-foreground">{level}</p>
                <p className="text-lg font-semibold tabular-nums">{bySeverity[level] ?? 0}</p>
              </div>
            ))}
          </div>
        </section>

        <div className="grid grid-cols-2 gap-3">
          <StatCard label="Findings" value={payload.summary.issues} icon={AlertTriangle} tone="warning" />
          <StatCard label="Avg complexity" value={Number(metrics.avg_complexity ?? 0)} hint={`max ${metrics.max_complexity ?? 0}`} icon={Activity} />
          <StatCard label="Test ratio" value={`${Math.round(Number(metrics.test_file_ratio ?? 0) * 100)}%`} hint="test files / all files" icon={ShieldCheck} />
          <StatCard label="Cycles" value={Number(metrics.cycles ?? 0)} hint={`${metrics.orphans ?? 0} isolated modules`} icon={Gauge} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter findings…"
            className="h-8 w-64 pl-8 text-xs"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setSeverity(null)}
            className={cn(
              "rounded-md border px-2 py-0.5 text-2xs transition-colors",
              severity === null ? "border-primary/40 bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            all severities
          </button>
          {Object.entries(bySeverity).map(([level, count]) => (
            <button
              key={level}
              type="button"
              onClick={() => setSeverity(level)}
              className={cn(
                "rounded-md border px-2 py-0.5 text-2xs transition-colors",
                severity === level ? "border-primary/40 bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {level} ({count})
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setKind(null)}
            className={cn(
              "rounded-md border px-2 py-0.5 text-2xs transition-colors",
              kind === null ? "border-primary/40 bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            all kinds
          </button>
          {Object.entries(payload.summary.by_kind).map(([name, count]) => (
            <button
              key={name}
              type="button"
              onClick={() => setKind(name)}
              className={cn(
                "rounded-md border px-2 py-0.5 text-2xs transition-colors",
                kind === name ? "border-primary/40 bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {KIND_LABELS[name] ?? name} ({count})
            </button>
          ))}
        </div>
      </div>

      <section className="panel overflow-hidden">
        <div className="panel-header">
          <span className="panel-title">Findings</span>
          <span className="text-2xs text-muted-foreground">
            {issues.length} of {payload.issues.length} shown
          </span>
        </div>
        {issues.length === 0 ? (
          <p className="px-5 py-10 text-center text-xs text-muted-foreground">
            No findings match the current filters. An empty list here means the heuristics found nothing above the
            configured thresholds — not that the code is defect free.
          </p>
        ) : (
          <ul>
            {issues.slice(0, 80).map((issue) => (
              <IssueRow key={issue.id} issue={issue} />
            ))}
          </ul>
        )}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="panel">
          <div className="panel-header">
            <span className="panel-title">Metrics</span>
          </div>
          <ul className="divide-y divide-border">
            {Object.entries(metrics)
              .filter(([, value]) => typeof value === "number")
              .map(([key, value]) => (
                <li key={key} className="flex items-center justify-between px-5 py-2 text-xs">
                  <span className="text-muted-foreground">{key.replace(/_/g, " ")}</span>
                  <span className="tabular-nums">{Number(value).toLocaleString()}</span>
                </li>
              ))}
          </ul>
        </section>

        <section className="panel">
          <div className="panel-header">
            <span className="panel-title">Thresholds in effect</span>
            <Badge variant="outline" className="font-normal">
              configurable via env
            </Badge>
          </div>
          <ul className="divide-y divide-border">
            {Object.entries(thresholds).map(([key, value]) => (
              <li key={key} className="flex items-center justify-between px-5 py-2 text-xs">
                <span className="text-muted-foreground">{key.replace(/_/g, " ")}</span>
                <span className="tabular-nums">{value}</span>
              </li>
            ))}
          </ul>
          <div className="p-5 pt-4">
            <InlineNote className="flex items-start gap-2">
              <Info className="mt-0.5 size-3.5 shrink-0" />
              <span>{payload.disclaimer}</span>
            </InlineNote>
          </div>
        </section>
      </div>
    </div>
  );
}

export default function QualityPage() {
  return (
    <RunGate title="Analyse a repository to review its code quality">
      <QualityBody />
    </RunGate>
  );
}
