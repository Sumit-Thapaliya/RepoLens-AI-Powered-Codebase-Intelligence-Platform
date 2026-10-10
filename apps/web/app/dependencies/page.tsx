"use client";

import * as React from "react";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertOctagon, Blocks, ExternalLink, Search, Unplug } from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { DependencyGraph, GraphNodeDetail } from "@/components/dependencies/dependency-graph";
import { StatCard } from "@/components/common/kpi";
import { PathLink } from "@/components/common/path-link";
import { Badge } from "@/components/ui/badge";
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
  const limit = view === "files" ? 220 : 120;
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

  const visibleNodes = layerFilter ? payload.nodes.filter((node) => node.layer === layerFilter) : payload.nodes;
  const visibleEdges = layerFilter
    ? payload.edges.filter((edge) => visibleNodes.some((node) => node.id === edge.source) && visibleNodes.some((node) => node.id === edge.target))
    : payload.edges;

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-base font-semibold tracking-tight">Dependencies</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Import and call relationships resolved across {formatNumber(Number(stats.files ?? 0))} code modules.
            Circular dependencies, hubs and isolated modules are computed from this graph.
            {Number(stats.excluded_files ?? 0) > 0
              ? ` ${formatNumber(Number(stats.excluded_files))} documentation, data and asset files are excluded - they cannot import anything.`
              : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {layerFilter ? (
            <button
              type="button"
              className="rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-2xs text-primary"
              onClick={() => router.push("/dependencies")}
            >
              layer filter: {layerLabel(layerFilter)} ✕
            </button>
          ) : null}
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="Highlight nodes…"
              className="h-8 w-56 pl-8 text-xs"
            />
          </div>
          <Tabs value={view} onValueChange={(value) => setView(value as "files" | "modules")}>
            <TabsList>
              <TabsTrigger value="files">Files</TabsTrigger>
              <TabsTrigger value="modules">Modules</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
        <StatCard label="Nodes" value={Number(stats.files ?? payload.nodes.length)} hint={`${payload.edges.length} edges in view`} icon={Blocks} tone="primary" />
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
          <DependencyGraph
            payload={{ ...payload, nodes: visibleNodes, edges: visibleEdges }}
            moduleView={view === "modules"}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
            onOpenFile={openFile}
            searchTerm={searchTerm}
          />
          <InlineNote>
            Solid arrows are imports, dashed arrows are resolved calls. Layout groups files by architectural layer and is
            stable across reloads; edges come from the parser's resolver, not from naming guesses.
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
                No import cycle was found. Cycles are detected with Tarjan's algorithm on the resolved import graph.
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
