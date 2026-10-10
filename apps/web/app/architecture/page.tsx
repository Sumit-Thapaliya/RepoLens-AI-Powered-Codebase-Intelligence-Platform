"use client";

import * as React from "react";
import { CornerDownRight, Network } from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { ArchitectureFlow, ArchitectureLegend } from "@/components/architecture/architecture-graph";
import { PathLink } from "@/components/common/path-link";
import { ErrorState, InlineNote, SectionHeading, SkeletonCard } from "@/components/ui/states";
import { Badge } from "@/components/ui/badge";
import { getArchitecture } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { cn, formatNumber, layerColor } from "@/lib/utils";

function ArchitectureBody() {
  const { analysisId } = useAnalysisContext();
  const { data: graph, error, isLoading: loading, mutate } = useApi(
    analysisId ? `architecture:${analysisId}` : null,
    () => getArchitecture(analysisId!),
  );
  const load = React.useCallback(async () => {
    await mutate();
  }, [mutate]);

  if (loading && !graph) return <SkeletonCard className="m-6" lines={10} />;
  if (error && !graph) return <ErrorState error={error} onRetry={() => void load()} className="m-6" />;
  if (!graph) return null;

  const totalFiles = graph.layers.reduce((sum, layer) => sum + layer.files, 0);

  return (
    <div className="space-y-5 p-4 lg:p-6">
      <SectionHeading
        title="Architecture"
        detail={`${graph.layers.length} layers · ${formatNumber(totalFiles)} files · ${graph.edges.length} inter-layer connections`}
        right={<Badge variant="secondary">heuristic layers</Badge>}
      />

      <ArchitectureFlow graph={graph} />
      <ArchitectureLegend notes={graph.notes} />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <section className="panel overflow-hidden">
          <div className="panel-header">
            <span className="panel-title">Layer breakdown</span>
            <span className="text-2xs text-muted-foreground">files, symbols and coupling per layer</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left text-2xs uppercase tracking-wider text-muted-foreground">
                  <th className="px-5 py-2 font-medium">Layer</th>
                  <th className="px-3 py-2 text-right font-medium">Files</th>
                  <th className="px-3 py-2 text-right font-medium">LOC</th>
                  <th className="px-3 py-2 text-right font-medium">Symbols</th>
                  <th className="px-3 py-2 text-right font-medium">Fan-in</th>
                  <th className="px-3 py-2 text-right font-medium">Fan-out</th>
                  <th className="px-3 py-2 text-right font-medium">Internal edges</th>
                  <th className="px-5 py-2 font-medium">Example</th>
                </tr>
              </thead>
              <tbody>
                {graph.layers.map((layer) => (
                  <tr key={layer.id} className="border-b border-border/60 last:border-0">
                    <td className="px-5 py-2.5">
                      <span className="flex items-center gap-2">
                        <span className="size-2 rounded-full" style={{ backgroundColor: layerColor(layer.id) }} />
                        <span className="font-medium">{layer.label}</span>
                      </span>
                      <span className="mt-0.5 block max-w-md text-2xs text-muted-foreground">{layer.description}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{layer.files}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{formatNumber(layer.loc)}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{layer.symbols}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{layer.fan_in}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{layer.fan_out}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{layer.internal_edges}</td>
                    <td className="px-5 py-2.5">
                      {layer.sample_files[0] ? <PathLink path={layer.sample_files[0].path} compact /> : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <div className="space-y-4">
          <section className="panel">
            <div className="panel-header">
              <span className="panel-title flex items-center gap-2">
                <CornerDownRight className="size-3.5 text-muted-foreground" /> Entry points
              </span>
              <span className="text-2xs text-muted-foreground">{graph.entrypoints.length} detected</span>
            </div>
            <ul className="divide-y divide-border">
              {graph.entrypoints.slice(0, 12).map((entry) => (
                <li key={entry.path} className="flex items-center justify-between gap-3 px-5 py-2.5">
                  <div className="min-w-0">
                    <PathLink path={entry.path} compact={false} showLine={false} className="max-w-full" />
                    <p className="mt-0.5 text-2xs text-muted-foreground">
                      {entry.kind} · {entry.detail}
                    </p>
                  </div>
                  <span
                    className={cn("shrink-0 rounded border px-1.5 py-0.5 text-2xs")}
                    style={{ color: layerColor(entry.layer), borderColor: `${layerColor(entry.layer)}55` }}
                  >
                    {entry.layer}
                  </span>
                </li>
              ))}
              {graph.entrypoints.length === 0 ? (
                <li className="px-5 py-6 text-center text-xs text-muted-foreground">No process entry points detected.</li>
              ) : null}
            </ul>
          </section>

          <section className="panel">
            <div className="panel-header">
              <span className="panel-title flex items-center gap-2">
                <Network className="size-3.5 text-muted-foreground" /> Layer connections
              </span>
            </div>
            <ul className="max-h-96 space-y-1.5 overflow-y-auto p-4 scrollbar-thin">
              {graph.edges
                .slice()
                .sort((a, b) => b.weight - a.weight)
                .map((edge) => (
                  <li key={`${edge.source}-${edge.target}`} className="rounded-lg border border-border/70 px-3 py-2">
                    <p className="flex items-center gap-2 text-2xs">
                      <span className="font-medium" style={{ color: layerColor(edge.source) }}>
                        {edge.source}
                      </span>
                      <span className="text-muted-foreground">→</span>
                      <span className="font-medium" style={{ color: layerColor(edge.target) }}>
                        {edge.target}
                      </span>
                      <span className="ml-auto text-muted-foreground">{edge.weight} links</span>
                    </p>
                    <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-2xs text-muted-foreground">
                      <span>kinds: {edge.kinds.join(", ")}</span>
                      {edge.samples[0] ? <span className="mono truncate">{edge.samples[0].source}</span> : null}
                    </p>
                  </li>
                ))}
            </ul>
          </section>

          <InlineNote>
            Layers come from path conventions (directories, file stems) and from import/call edges resolved in the parser.
            They are heuristic: a file such as <span className="mono">services/auth.ts</span> is classified as a service
            because of its directory and name, while <span className="mono">core/security.ts</span> is treated as
            middleware. Nothing here is generated by an LLM.
          </InlineNote>
        </div>
      </div>
    </div>
  );
}

export default function ArchitecturePage() {
  return (
    <RunGate title="Analyse a repository to see its architecture">
      <ArchitectureBody />
    </RunGate>
  );
}
