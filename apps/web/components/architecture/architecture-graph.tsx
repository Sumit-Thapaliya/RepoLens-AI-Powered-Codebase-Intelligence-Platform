"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ChevronRight, Info, Layers } from "lucide-react";
import type { ArchitectureGraph } from "@/lib/types";
import { cn, layerColor, layerLabel } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type LayerNodeData = {
  id: string;
  label: string;
  description: string;
  files: number;
  symbols: number;
  loc: number;
  fanIn: number;
  fanOut: number;
  samples: { path: string; loc: number }[];
  onSelect: (id: string) => void;
  selected: boolean;
};

function LayerNode({ data }: NodeProps<Node<LayerNodeData>>) {
  const color = layerColor(data.id);
  return (
    <div
      onClick={() => data.onSelect(data.id)}
      style={{ borderColor: data.selected ? color : undefined, boxShadow: data.selected ? `0 0 0 1px ${color}55, 0 12px 40px -18px ${color}` : undefined }}
      className={cn(
        "w-[15.5rem] cursor-pointer rounded-xl border bg-surface/95 p-3.5 backdrop-blur transition-all hover:border-primary/50",
        data.selected ? "border-transparent" : "border-border",
      )}
    >
      <Handle type="target" position={Position.Left} className="!bg-border" />
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-xs font-semibold">
          <span className="size-2 rounded-full" style={{ backgroundColor: color }} />
          {data.label}
        </span>
        <Badge variant="outline" className="mono">{data.files}</Badge>
      </div>
      <p className="mt-1.5 line-clamp-2 text-2xs leading-relaxed text-muted-foreground">{data.description}</p>
      <div className="mt-2.5 flex items-center gap-3 text-2xs text-muted-foreground">
        <span>{data.symbols} symbols</span>
        <span>{data.loc.toLocaleString()} loc</span>
      </div>
      <div className="mt-2 flex items-center gap-2 text-2xs">
        <span className="rounded border border-border px-1.5 py-0.5 text-muted-foreground">in {data.fanIn}</span>
        <span className="rounded border border-border px-1.5 py-0.5 text-muted-foreground">out {data.fanOut}</span>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-border" />
    </div>
  );
}

const nodeTypes = { layer: LayerNode };

function layout(graph: ArchitectureGraph): { nodes: Node<LayerNodeData>[]; edges: Edge[] } {
  const columns: string[][] = [
    ["ui", "entrypoint"],
    ["route", "middleware"],
    ["service", "util"],
    ["repository"],
    ["config", "test", "other"],
  ];
  const byLayer = new Map(graph.layers.map((layer) => [layer.id, layer]));
  const placed = new Set<string>();
  const ordered: { id: string; column: number }[] = [];

  columns.forEach((group, columnIndex) => {
    group.forEach((layerId) => {
      if (byLayer.has(layerId)) {
        ordered.push({ id: layerId, column: columnIndex });
        placed.add(layerId);
      }
    });
  });
  graph.layers
    .filter((layer) => !placed.has(layer.id))
    .forEach((layer) => ordered.push({ id: layer.id, column: 4 }));

  const columnHeights = new Map<number, number>();
  const nodes: Node<LayerNodeData>[] = ordered.map(({ id, column }) => {
    const layer = byLayer.get(id)!;
    const index = columnHeights.get(column) ?? 0;
    columnHeights.set(column, index + 1);
    return {
      id,
      type: "layer",
      position: { x: column * 300, y: index * 210 },
      data: {
        id,
        label: layer.label,
        description: layer.description,
        files: layer.files,
        symbols: layer.symbols,
        loc: layer.loc,
        fanIn: layer.fan_in,
        fanOut: layer.fan_out,
        samples: layer.sample_files ?? [],
        onSelect: () => {},
        selected: false,
      },
    };
  });

  const edges: Edge[] = graph.edges.map((edge) => ({
    id: `${edge.source}->${edge.target}`,
    source: edge.source,
    target: edge.target,
    animated: false,
    label: String(edge.weight),
    labelStyle: { fill: "#94a3b8", fontSize: 10 },
    labelBgStyle: { fill: "#11141a" },
    style: { stroke: "#334155", strokeWidth: Math.min(1 + Math.log2(edge.weight + 1), 4) },
    data: edge,
  }));

  return { nodes, edges };
}

export function ArchitectureFlow({ graph }: { graph: ArchitectureGraph }) {
  const router = useRouter();
  const [selected, setSelected] = React.useState<string | null>(graph.layers[0]?.id ?? null);
  const base = React.useMemo(() => layout(graph), [graph]);

  const nodes = React.useMemo(
    () =>
      base.nodes.map((node) => ({
        ...node,
        data: {
          ...node.data,
          selected: node.id === selected,
          onSelect: (id: string) => setSelected(id),
        },
      })),
    [base.nodes, selected],
  );

  const activeLayer = graph.layers.find((layer) => layer.id === selected) ?? null;
  const activeEdges = graph.edges.filter((edge) => edge.source === selected || edge.target === selected);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="panel relative h-[30rem] overflow-hidden">
        <ReactFlowProvider>
          <ReactFlow
            nodes={nodes}
            edges={base.edges}
            nodeTypes={nodeTypes}
            fitView
            minZoom={0.35}
            maxZoom={1.6}
            proOptions={{ hideAttribution: true }}
            className="bg-transparent"
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="hsl(220 12% 22%)" />
            <Controls showInteractive={false} className="!bottom-3 !left-3" />
            <MiniMap
              pannable
              zoomable
              className="!bottom-3 !right-3 !h-24 !w-36 !rounded-lg !border !border-border"
              nodeColor={(node) => layerColor(node.id as string)}
              maskColor="hsl(220 14% 6% / 0.7)"
            />
          </ReactFlow>
        </ReactFlowProvider>
        <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-2 rounded-md border border-border bg-surface/90 px-2.5 py-1 text-2xs text-muted-foreground">
          <Layers className="size-3" /> Click a layer to inspect it · scroll to zoom · drag to pan
        </div>
      </div>

      <div className="panel flex max-h-[30rem] flex-col overflow-hidden">
        <div className="panel-header">
          <span className="panel-title">{activeLayer ? activeLayer.label : "Layer detail"}</span>
          {activeLayer ? (
            <Button size="xs" variant="outline" onClick={() => router.push(`/dependencies?layer=${activeLayer.id}`)}>
              Open <ChevronRight className="size-3" />
            </Button>
          ) : null}
        </div>
        {activeLayer ? (
          <div className="flex-1 overflow-y-auto p-4 scrollbar-thin">
            <p className="text-xs leading-relaxed text-muted-foreground">{activeLayer.description}</p>
            <div className="mt-3 grid grid-cols-2 gap-2 text-2xs">
              <div className="rounded-md border border-border bg-surface-muted/50 px-2.5 py-2">
                <p className="text-muted-foreground">Files</p>
                <p className="text-sm font-semibold tabular-nums">{activeLayer.files}</p>
              </div>
              <div className="rounded-md border border-border bg-surface-muted/50 px-2.5 py-2">
                <p className="text-muted-foreground">LOC</p>
                <p className="text-sm font-semibold tabular-nums">{activeLayer.loc.toLocaleString()}</p>
              </div>
              <div className="rounded-md border border-border bg-surface-muted/50 px-2.5 py-2">
                <p className="text-muted-foreground">Fan-in</p>
                <p className="text-sm font-semibold tabular-nums">{activeLayer.fan_in}</p>
              </div>
              <div className="rounded-md border border-border bg-surface-muted/50 px-2.5 py-2">
                <p className="text-muted-foreground">Fan-out</p>
                <p className="text-sm font-semibold tabular-nums">{activeLayer.fan_out}</p>
              </div>
            </div>

            <p className="mt-4 text-2xs uppercase tracking-wider text-muted-foreground">Most connected files</p>
            <ul className="mt-2 space-y-1">
              {activeLayer.sample_files.slice(0, 8).map((file) => (
                <li key={file.path}>
                  <button
                    type="button"
                    onClick={() => router.push(`/explorer?path=${encodeURIComponent(file.path)}`)}
                    className="flex w-full items-center justify-between gap-2 rounded-md border border-border/70 px-2 py-1.5 text-left transition-colors hover:border-primary/40"
                  >
                    <span className="mono truncate text-2xs">{file.path}</span>
                    <span className="shrink-0 text-2xs text-muted-foreground">{file.fan_in} in</span>
                  </button>
                </li>
              ))}
            </ul>

            {activeEdges.length ? (
              <>
                <p className="mt-4 text-2xs uppercase tracking-wider text-muted-foreground">Connections</p>
                <ul className="mt-2 space-y-1.5">
                  {activeEdges.map((edge) => (
                    <li key={`${edge.source}-${edge.target}`} className="rounded-md border border-border/70 px-2 py-1.5">
                      <p className="flex items-center gap-1.5 text-2xs">
                        <span className="font-medium">{layerLabel(edge.source)}</span>
                        <ChevronRight className="size-3 text-muted-foreground" />
                        <span className="font-medium">{layerLabel(edge.target)}</span>
                        <span className="ml-auto text-muted-foreground">{edge.weight} imports</span>
                      </p>
                      {edge.samples[0] ? (
                        <p className="mono mt-1 truncate text-2xs text-muted-foreground">{edge.samples[0].source}</p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ArchitectureLegend({ notes }: { notes: string[] }) {
  if (!notes.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-muted-foreground">
      <span className="flex items-center gap-1">
        <Info className="size-3" /> How this view is built:
      </span>
      {notes.map((note) => (
        <span key={note}>{note}</span>
      ))}
    </div>
  );
}
