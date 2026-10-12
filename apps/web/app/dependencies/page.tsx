"use client";

import * as React from "react";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertOctagon, Blocks, ExternalLink, Minus, Plus, Search, Unplug } from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { DependencyGraph, GraphNodeDetail } from "@/components/dependencies/dependency-graph";
import { StatCard } from "@/components/common/kpi";
import { PathLink } from "@/components/common/path-link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ErrorState, InlineNote, SkeletonCard } from "@/components/ui/states";
import { getDependencies } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { GraphNode } from "@/lib/types";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { formatNumber, layerLabel } from "@/lib/utils";

function DependenciesBody() {
  const { analysisId } = useAnalysisContext();
  const searchParams = useSearchParams();
  const router = useRouter();
  const layerFilter = searchParams.get("layer");

  const [view, setView] = React.useState<"files" | "modules">("files");
  const [selected, setSelected] = React.useState<GraphNode | null>(null);
  const [searchTerm, setSearchTerm] = React.useState("");
  const [limit, setLimit] = React.useState(64);
  const initialLimit = view === "files" ? 64 : 48;
  const maxLimit = 256;
  const { data: payload, error, isLoading: loading, mutate } = useApi(
    analysisId ? `dependencies:${analysisId}:${view}:${limit}` : null,
    () => getDependencies(analysisId!, view, limit),
  );
  const load = React.useCallback(async () => {
    await mutate();
  }, [mutate]);

  React.useEffect(() => {
    if (!payload || !layerFilter) return;
    const first = payload.nodes.find((node) => node.layer === layerFilter);
    if (first) setSelected(first);
  }, [payload, layerFilter]);

  const openFile = (path: string) => router.push(`/explorer?path=${encodeURIComponent(path)}`);
  const changeView = (value: string) => {
    const next = value as "files" | "modules";
    setView(next);
    setLimit(next === "files" ? 64 : 48);
    setSelected(null);
  };

  if (loading && !payload) {
    return (
      <div className="space-y-4 p-4 lg:p-6">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <SkeletonCard key={index} lines={2} />
          ))}
        </div>
        <SkeletonCard lines={12} />
      </div>
    );
  }
  if (error && !payload) return <ErrorState error={error} onRetry={() => void load()} className="m-6" />;
  if (!payload) return null;

  const stats = payload.stats;
  const cycles = payload.cycles ?? [];
  const orphans = payload.orphans ?? [];
  const modules = payload.module_stats ?? [];
  const totalNodes = Number(stats.total_nodes ?? stats.nodes ?? payload.nodes.length);
  const shownNodes = Number(stats.shown_nodes ?? payload.nodes.length);
  const graphTruncated = Boolean(stats.truncated);

  const visibleNodes = layerFilter ? payload.nodes.filter((node) => node.layer === layerFilter) : payload.nodes;
  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = layerFilter
    ? payload.edges.filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
    : payload.edges;

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 text-accent shadow-[0_0_24px_-12px_hsl(var(--accent)/0.65)]">
            <Blocks className="size-5" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">Dependencies</h1>
              <Badge variant="outline" className="tabular-nums">{formatNumber(totalNodes)} nodes</Badge>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-muted-foreground">
              Imports and resolved calls across {formatNumber(Number(stats.files ?? totalNodes))} code modules. Circular dependencies,
              hubs and isolated modules are computed from the resolved graph.
              {Number(stats.excluded_files ?? 0) > 0
                ? ` ${formatNumber(Number(stats.excluded_files))} documentation, data and asset files are excluded.`
                : ""}
            </p>
          </div>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 xl:w-auto xl:justify-end">
          {layerFilter ? (
            <button
              type="button"
              className="rounded-lg border border-primary/35 bg-primary/10 px-2.5 py-1.5 text-2xs text-primary transition-colors hover:bg-primary/15"
              onClick={() => router.push("/dependencies")}
            >
              {layerLabel(layerFilter)} <span aria-hidden="true">×</span>
            </button>
          ) : null}
          <div className="relative min-w-[12rem] flex-1 sm:max-w-64 xl:flex-none">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="Highlight nodes…"
              aria-label="Highlight dependency nodes"
              className="h-9 pl-8 text-xs"
            />
          </div>
          <Tabs value={view} onValueChange={changeView}>
            <TabsList>
              <TabsTrigger value="files">Files</TabsTrigger>
              <TabsTrigger value="modules">Modules</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
        <StatCard label="Nodes" value={totalNodes} hint={`${shownNodes} nodes loaded into the graph preview`} icon={Blocks} tone="primary" />
        <StatCard label="Import edges" value={Number(stats.import_edges ?? 0)} />
        <StatCard label="Call edges" value={Number(stats.call_edges ?? 0)} hint="Resolved cross-file calls" />
        <StatCard
          label="Cycles"
          value={cycles.length}
          hint={cycles.length ? "Circular import chains detected" : "No circular imports"}
          tone={cycles.length ? "warning" : "default"}
          icon={AlertOctagon}
        />
        <StatCard label="Hubs" value={Number(stats.hubs ?? payload.hubs.length)} hint="High fan-in / fan-out files" />
        <StatCard
          label="Isolated"
          value={Number(stats.orphans ?? orphans.length)}
          hint="Code modules with no resolved edges (may be entrypoints or dynamically loaded)"
          icon={Unplug}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 px-0.5">
            <p className="text-2xs text-muted-foreground">
              Graph preview <span className="mx-1 text-border">·</span>
              <span className="font-medium tabular-nums text-foreground">{visibleNodes.length}</span> of {formatNumber(totalNodes)} nodes
              {layerFilter ? ` · ${layerLabel(layerFilter)} layer` : ""}
            </p>
            <div className="flex items-center gap-1.5">
              {limit > initialLimit ? (
                <Button variant="ghost" size="xs" onClick={() => setLimit(initialLimit)}>
                  <Minus /> Compact
                </Button>
              ) : null}
              {graphTruncated && limit < maxLimit ? (
                <Button variant="outline" size="xs" onClick={() => setLimit((current) => Math.min(maxLimit, current + 64))}>
                  <Plus /> Show more
                </Button>
              ) : null}
              {graphTruncated && limit >= maxLimit ? (
                <span className="text-2xs text-muted-foreground">Preview capped at {maxLimit}</span>
              ) : null}
            </div>
          </div>
          <DependencyGraph
            payload={{ ...payload, nodes: visibleNodes, edges: visibleEdges }}
            moduleView={view === "modules"}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
            searchTerm={searchTerm}
          />
          <InlineNote>
            Solid arrows are imports, dashed arrows are resolved calls. Layout groups files by architectural layer and is
            stable across reloads; edges come from the parser&apos;s resolver, not from naming guesses.
          </InlineNote>
        </div>

        <div className="space-y-4">
          {selected ? <GraphNodeDetail node={selected} payload={payload} onOpenFile={openFile} /> : null}

          <section className="panel">
            <div className="panel-header">
              <span className="panel-title flex items-center gap-2">
                <AlertOctagon className="size-3.5 text-rose-300" /> Circular dependencies
              </span>
              <Badge variant={cycles.length ? "danger" : "success"}>{cycles.length}</Badge>
            </div>
            {cycles.length === 0 ? (
              <p className="p-4 text-2xs text-muted-foreground">
                No import cycle was found. Cycles are detected with Tarjan&apos;s algorithm on the resolved import graph.
              </p>
            ) : (
              <ul className="max-h-56 divide-y divide-border overflow-y-auto scrollbar-thin">
                {cycles.map((cycle) => (
                  <li key={cycle.id} className="px-4 py-2.5">
                    <p className="text-2xs text-muted-foreground">{cycle.size} file(s)</p>
                    <ul className="mt-1 space-y-0.5">
                      {cycle.paths.slice(0, 5).map((path) => (
                        <li key={path}>
                          <PathLink path={path} showLine={false} />
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="panel">
            <div className="panel-header">
              <span className="panel-title">Most coupled files</span>
              <span className="text-2xs text-muted-foreground">{payload.hubs.length} hubs</span>
            </div>
            <ul className="max-h-64 divide-y divide-border overflow-y-auto scrollbar-thin">
              {payload.hubs.slice(0, 12).map((hub) => (
                <li key={hub.id} className="flex items-center justify-between gap-2 px-4 py-2">
                  <button type="button" className="min-w-0 text-left" onClick={() => setSelected(hub)}>
                    <span className="mono block truncate text-2xs">{hub.path}</span>
                    <span className="text-2xs text-muted-foreground">
                      {layerLabel(hub.layer)} · {hub.symbols ?? 0} symbols
                    </span>
                  </button>
                  <span className="shrink-0 text-2xs tabular-nums text-muted-foreground">
                    {hub.fan_in ?? 0} in / {hub.fan_out ?? 0} out
                  </span>
                </li>
              ))}
              {payload.hubs.length === 0 ? <li className="px-4 py-4 text-center text-2xs text-muted-foreground">No hubs detected.</li> : null}
            </ul>
          </section>

          {view === "modules" && modules.length ? (
            <section className="panel">
              <div className="panel-header">
                <span className="panel-title">Module summary</span>
              </div>
              <ul className="max-h-64 divide-y divide-border overflow-y-auto scrollbar-thin">
                {modules.slice(0, 12).map((module) => (
                  <li key={module.module} className="px-4 py-2 text-2xs">
                    <span className="mono block truncate">{module.module}</span>
                    <span className="text-muted-foreground">
                      {module.files} files · {formatNumber(module.loc)} loc · {module.fan_in} in / {module.fan_out} out
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {payload.external_dependencies?.length ? (
            <section className="panel">
              <div className="panel-header">
                <span className="panel-title flex items-center gap-2">
                  <ExternalLink className="size-3.5 text-muted-foreground" /> External packages
                </span>
              </div>
              <ul className="max-h-56 divide-y divide-border overflow-y-auto scrollbar-thin">
                {payload.external_dependencies.slice(0, 14).map((dependency) => (
                  <li key={dependency.name} className="flex items-center justify-between gap-2 px-4 py-1.5 text-2xs">
                    <span className="mono truncate">{dependency.name}</span>
                    <span className="tabular-nums text-muted-foreground">{dependency.imports}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </div>

      {payload.note ? <InlineNote>{payload.note}</InlineNote> : null}
    </div>
  );
}

export default function DependenciesPage() {
  return (
    <RunGate title="Analyse a repository to inspect its dependency graph">
      <Suspense fallback={<SkeletonCard className="m-6" lines={10} />}>
        <DependenciesBody />
      </Suspense>
    </RunGate>
  );
}
