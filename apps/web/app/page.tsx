"use client";

import * as React from "react";
import {
  Boxes,
  CircleDot,
  Database,
  FileCode2,
  FunctionSquare,
  GitBranch,
  Layers,
  Route,
  ShieldCheck,
  TriangleAlert,
  Workflow as WorkflowIcon,
} from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { StatCard } from "@/components/common/kpi";
import { RepoHeader } from "@/components/overview/repo-header";
import { DependencyCard, DiagnosticsCard, DatabaseStackCard, FrameworksCard, LanguageCard } from "@/components/overview/stack-cards";
import { InsightsPanel } from "@/components/insights/insights-panel";
import { RecentAnalyses } from "@/components/runs/recent-analyses";
import { ArchitectureFlow, ArchitectureLegend } from "@/components/architecture/architecture-graph";
import { ErrorState, SectionHeading, SkeletonCard } from "@/components/ui/states";
import { Button } from "@/components/ui/button";
import { getArchitecture, getOverview } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { formatNumber } from "@/lib/utils";
import { useAnalysisContext } from "@/components/providers/analysis-provider";

function Section({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={className}>{children}</div>;
}

function OverviewBody() {
  const { analysisId, analysis } = useAnalysisContext();
  const { data, error, isLoading, mutate } = useApi(
    analysisId ? `overview:${analysisId}` : null,
    async () => {
      const [overview, architecture] = await Promise.all([
        getOverview(analysisId!),
        getArchitecture(analysisId!),
      ]);
      return { overview, architecture };
    },
  );
  const overview = data?.overview ?? null;
  const architecture = data?.architecture ?? null;
  const loading = isLoading;
  const load = React.useCallback(async () => {
    await mutate();
  }, [mutate]);

  if (loading && !overview) {
    return (
      <div className="grid gap-4 p-4 lg:grid-cols-3 lg:p-6">
        <SkeletonCard className="lg:col-span-3" lines={2} />
        {Array.from({ length: 6 }).map((_, index) => (
          <SkeletonCard key={index} lines={2} />
        ))}
      </div>
    );
  }

  if (error && !overview) {
    return <ErrorState error={error} onRetry={() => void load()} title="Could not load the overview" className="m-6" />;
  }

  if (!overview || !analysis) return null;

  const { endpoint_stats: endpoints, database_stats: database, quality, graph_stats: graph } = overview;

  return (
    <div className="space-y-5 p-4 lg:p-6">
      <RepoHeader repo={overview.repo} run={analysis} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
        <StatCard label="Files" value={overview.files} hint={`${overview.parsed_files} parsed with tree-sitter / AST`} icon={FileCode2} tone="primary" />
        <StatCard label="Lines of code" value={overview.loc} hint="Counted on parsed source files only" icon={Layers} />
        <StatCard label="Functions" value={overview.functions} hint={`${overview.symbols} symbols in total`} icon={FunctionSquare} />
        <StatCard label="Classes" value={overview.classes} hint="Classes, interfaces and types" icon={Boxes} href="/dependencies" />
        <StatCard label="API endpoints" value={endpoints.total} hint={`${endpoints.authenticated} require authentication`} icon={Route} tone="accent" href="/apis" />
        <StatCard label="Workflows" value={overview.workflows} hint="Traced from UI/handler entry points" icon={WorkflowIcon} href="/workflows" />
        <StatCard
          label="DB models"
          value={database.models ?? 0}
          hint={`${database.queries ?? 0} queries · ${database.migrations ?? 0} migrations`}
          icon={Database}
          href="/database"
        />
        <StatCard label="Graph edges" value={overview.edges} hint={`${graph.orphans ?? 0} isolated files`} icon={CircleDot} href="/dependencies" />
        <StatCard
          label="Circular deps"
          value={overview.circular_dependencies}
          hint={overview.circular_dependencies ? "Cycles detected — open Dependencies" : "No import cycles detected"}
          icon={GitBranch}
          tone={overview.circular_dependencies ? "warning" : "default"}
          href="/dependencies"
        />
        <StatCard
          label="Quality score"
          value={quality.health_score}
          hint={`${quality.issues} heuristic findings · ${quality.health_label}`}
          icon={ShieldCheck}
          tone={quality.health_score >= 80 ? "primary" : "warning"}
          href="/quality"
        />
        <StatCard
          label="Code modules"
          value={Number((overview.graph_stats as { files?: number }).files ?? overview.modules)}
          hint={
            Number((overview.graph_stats as { excluded_files?: number }).excluded_files ?? 0) > 0
              ? `${formatNumber(overview.files)} files - ${formatNumber(Number((overview.graph_stats as { excluded_files?: number }).excluded_files ?? 0))} docs/assets excluded from the graph`
              : "Files that carry dependencies"
          }
          icon={Layers}
        />
        <StatCard
          label="Test files"
          value={overview.test_files}
          hint={overview.test_files ? "Tests detected and linked to impact analysis" : "No test files detected"}
          icon={ShieldCheck}
          href="/quality"
        />
      </div>

      <section>
        <SectionHeading
          title="Architecture"
          detail="Frontend → API → services → data, derived from the resolved dependency graph. Click any layer."
          right={
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => void load()} loading={loading}>
                Refresh
              </Button>
            </div>
          }
          className="mb-3"
        />
        {architecture ? (
          <>
            <ArchitectureFlow graph={architecture} />
            <div className="mt-3">
              <ArchitectureLegend notes={architecture.notes} />
            </div>
          </>
        ) : (
          <SkeletonCard lines={6} />
        )}
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <LanguageCard overview={overview} />
            <FrameworksCard overview={overview} />
            <DatabaseStackCard overview={overview} />
            <DependencyCard overview={overview} />
          </div>
          <DiagnosticsCard overview={overview} />

          {overview.hubs?.length ? (
            <section className="panel">
              <div className="panel-header">
                <span className="panel-title">Central files</span>
                <span className="text-2xs text-muted-foreground">sorted by fan-in (how much depends on them)</span>
              </div>
              <ul className="divide-y divide-border">
                {overview.hubs.slice(0, 8).map((hub) => (
                  <li key={hub.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
                    <div className="min-w-0">
                      <p className="mono truncate text-xs" title={hub.path ?? undefined}>
                        {hub.path}
                      </p>
                      <p className="text-2xs text-muted-foreground">
                        {hub.layer} · {hub.loc ?? 0} LOC · {hub.symbols ?? 0} symbols
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2 text-2xs">
                      <span className="rounded border border-border px-1.5 py-0.5 tabular-nums">in {hub.fan_in}</span>
                      <span className="rounded border border-border px-1.5 py-0.5 tabular-nums">out {hub.fan_out}</span>
                      <Button size="xs" variant="outline" asChild>
                        <a href={`/explorer?path=${encodeURIComponent(hub.path ?? "")}`}>Open</a>
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {overview.warnings?.length ? (
            <section className="panel">
              <div className="panel-header">
                <span className="panel-title flex items-center gap-2">
                  <TriangleAlert className="size-3.5 text-amber-300" /> Analysis warnings
                </span>
              </div>
              <ul className="space-y-1.5 p-5 pt-4">
                {overview.warnings.map((warning, index) => (
                  <li key={index} className="text-2xs text-muted-foreground">
                    <span className="mono text-amber-200/80">{warning.code}</span> — {warning.message}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>

        <div className="xl:sticky xl:top-[6.5rem] xl:self-start">
          <InsightsPanel insights={overview.insights} loading={loading} />
        </div>
      </div>

      <RecentAnalyses />
      <p className="px-1 text-2xs text-muted-foreground">
        {formatNumber(overview.symbols)} symbols, {formatNumber(overview.edges)} graph edges and {formatNumber(overview.loc)} lines of
        code are stored for this run. Limits in effect: {formatNumber(overview.limits.max_files ?? 0)} files,{" "}
        {formatNumber(overview.limits.max_file_bytes ?? 0)} bytes/file.
      </p>
    </div>
  );
}

export default function OverviewPage() {
  return (
    <RunGate title="Analyse a repository to see its overview">
      <OverviewBody />
    </RunGate>
  );
}
