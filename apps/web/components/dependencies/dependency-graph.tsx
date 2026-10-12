"use client";

import * as React from "react";
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
import type { DependenciesPayload, GraphEdge, GraphNode } from "@/lib/types";
import { cn, layerColor, layerLabel } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

const COLUMN_ORDER = [
  ["entrypoint", "route", "middleware"],
  ["service", "repository", "util"],
  ["ui"],
  ["config", "test", "other"],
];

type DepNodeData = {
  node: GraphNode;
  kind: "files" | "modules";
  highlighted: boolean;
  dimmed: boolean;
};

function FileNodeCard({ data }: NodeProps<Node<DepNodeData>>) {
  const { node, highlighted, dimmed } = data;
  const color = layerColor(node.layer);
  const cycle = Boolean(node.is_cycle_member);
  return (
    <div
      className={cn(
        "w-44 rounded-lg border bg-surface/95 px-2 py-1.5 shadow-sm backdrop-blur transition-all duration-200",
        dimmed ? "opacity-30" : "opacity-100",
        cycle ? "border-rose-500/60" : highlighted ? "border-primary/70 shadow-glow" : "border-border/90",
      )}
      style={highlighted ? { boxShadow: `0 0 0 1px color-mix(in srgb, ${color} 42%, transparent), 0 10px 30px -16px ${color}` } : undefined}
      title={node.path ?? node.id}
    >
      <Handle type="target" position={Position.Left} className="!bg-border" />
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[0.6875rem] font-medium">{node.label}</span>
        <span className="size-1.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-[0.625rem] text-muted-foreground">
        <span>{node.files ? `${node.files} files` : `${node.symbols ?? 0} sym`}</span>
        <span>·</span>
        <span>{node.loc ?? 0} loc</span>
        <span className="ml-auto tabular-nums">{node.fan_in ?? 0} in</span>
      </div>
      {cycle ? <span className="mt-1 block text-[0.625rem] text-rose-300">in cycle</span> : null}
      <Handle type="source" position={Position.Right} className="!bg-border" />
    </div>
  );
}

const nodeTypes = { dep: FileNodeCard };

function layoutNodes(nodes: GraphNode[], moduleView: boolean): Node<DepNodeData>[] {
  const columns = COLUMN_ORDER.map((group) => new Set(group));
  const lane = (layer: string) => {
    const index = columns.findIndex((set) => set.has(layer));
    return index === -1 ? 3 : index;
  };
  const counters = [0, 0, 0, 0];
  const ordered = [...nodes].sort((left, right) => {
    const leftWeight = left.coupling ?? (left.fan_in ?? 0) + (left.fan_out ?? 0);
    const rightWeight = right.coupling ?? (right.fan_in ?? 0) + (right.fan_out ?? 0);
    return rightWeight - leftWeight || left.label.localeCompare(right.label);
  });
  return ordered.map((node) => {
    const column = lane(node.layer);
    const index = counters[column]++;
    return {
      id: node.id,
      type: "dep",
      position: { x: column * 248, y: index * 76 },
      data: { node, kind: moduleView ? "modules" : "files", highlighted: false, dimmed: false },
      draggable: true,
    };
  });
}

export function DependencyGraph({
  payload,
  moduleView,
  selectedId,
  onSelect,
  searchTerm,
}: {
  payload: DependenciesPayload;
  moduleView: boolean;
  selectedId: string | null;
  onSelect: (node: GraphNode | null) => void;
  searchTerm: string;
}) {
  const nodes = React.useMemo(() => layoutNodes(payload.nodes, moduleView), [payload.nodes, moduleView]);
  const neighbours = React.useMemo(() => {
    if (!selectedId) return null;
    const set = new Set<string>([selectedId]);
    payload.edges.forEach((edge) => {
      if (edge.source === selectedId) set.add(edge.target);
      if (edge.target === selectedId) set.add(edge.source);
    });
    return set;
  }, [payload.edges, selectedId]);

  const needle = searchTerm.trim().toLowerCase();

  const decoratedNodes = React.useMemo(
    () =>
      nodes.map((node) => {
        const searchable = `${node.id} ${node.data.node.label} ${node.data.node.path ?? ""}`.toLowerCase();
        const matchesSearch = needle ? searchable.includes(needle) : false;
        const highlighted = needle
          ? matchesSearch
          : selectedId
            ? neighbours?.has(node.id) && node.id !== selectedId
            : false;
        const dimmed = Boolean(needle ? !matchesSearch : selectedId && !neighbours?.has(node.id));
        return { ...node, data: { ...node.data, highlighted, dimmed } };
      }),
    [nodes, needle, selectedId, neighbours],
  );

  const edges: Edge[] = React.useMemo(
    () =>
      payload.edges.map((edge: GraphEdge) => {
        const active = selectedId ? edge.source === selectedId || edge.target === selectedId : false;
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: "smoothstep",
          animated: false,
          label: active && edge.symbols?.length ? edge.symbols.slice(0, 2).join(", ") : undefined,
          labelStyle: { fill: "hsl(var(--muted-foreground))", fontSize: 9 },
          labelBgStyle: { fill: "hsl(var(--surface))" },
          style: {
            stroke: active ? "hsl(var(--primary))" : edge.kind === "call" ? "hsl(var(--accent) / 0.75)" : "hsl(var(--border))",
            strokeWidth: active ? 2 : 1,
            strokeDasharray: edge.kind === "call" ? "3 3" : undefined,
            opacity: selectedId && !active ? 0.16 : 1,
          },
        };
      }),
    [payload.edges, selectedId],
  );

  return (
    <div className="relative h-[27rem] overflow-hidden rounded-xl border border-border/90 bg-surface/50 shadow-card sm:h-[31rem]">
      <ReactFlowProvider>
        <ReactFlow
          nodes={decoratedNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.18, maxZoom: 1.1, duration: 450 }}
          minZoom={0.2}
          maxZoom={1.4}
          onNodeClick={(_, node) => onSelect(payload.nodes.find((entry) => entry.id === node.id) ?? null)}
          onPaneClick={() => onSelect(null)}
          proOptions={{ hideAttribution: true }}
          className="bg-transparent"
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="hsl(var(--border))" />
          <Controls showInteractive={false} className="!bottom-3 !left-3" />
          <MiniMap
            pannable
            zoomable
            className="!bottom-3 !right-3 !h-20 !w-32 !rounded-lg !border !border-border"
            nodeColor={(node) => layerColor((node.data as DepNodeData).node.layer)}
            maskColor="hsl(var(--background) / 0.75)"
          />
        </ReactFlow>
      </ReactFlowProvider>

      <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-1.5">
        <div className="rounded-md border border-border bg-surface/90 px-2.5 py-1 text-[0.625rem] text-muted-foreground">
          {payload.stats.shown_nodes ?? payload.nodes.length} of {payload.stats.total_nodes ?? payload.nodes.length}{" "}
          {moduleView ? "modules" : "files"} shown · drag to arrange · scroll to zoom
        </div>
        {payload.stats.truncated ? (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[0.625rem] text-amber-200">
            Graph truncated to the most connected nodes — the full edge list is in the analysis bundle.
          </div>
        ) : null}
      </div>

      <div className="pointer-events-none absolute right-3 top-3 flex flex-wrap gap-1.5">
        {[...new Set(payload.nodes.map((node) => node.layer))].slice(0, 8).map((layer) => (
          <Badge key={layer} variant="outline" className="font-normal" style={{ color: layerColor(layer) }}>
            {layerLabel(layer)}
          </Badge>
        ))}
      </div>
    </div>
  );
}

export function GraphNodeDetail({
  node,
  payload,
  onOpenFile,
}: {
  node: GraphNode;
  payload: DependenciesPayload;
  onOpenFile: (path: string) => void;
}) {
  const outgoing = payload.edges.filter((edge) => edge.source === node.id);
  const incoming = payload.edges.filter((edge) => edge.target === node.id);
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="min-w-0">
          <span className="mono block truncate text-xs">{node.path ?? node.id}</span>
          <span className="mt-0.5 block text-2xs text-muted-foreground">
            {layerLabel(node.layer)} · {node.loc ?? 0} loc · {node.symbols ?? 0} symbols
          </span>
        </div>
        {node.path ? (
          <button type="button" className="text-2xs text-primary hover:underline" onClick={() => onOpenFile(node.path!)}>
            open file
          </button>
        ) : null}
      </div>
      <div className="grid grid-cols-2 gap-2 p-4">
        <div className="rounded-md border border-border bg-surface-muted/40 px-2.5 py-2">
          <p className="text-2xs text-muted-foreground">Depends on</p>
          <p className="text-sm font-semibold tabular-nums">{outgoing.length}</p>
        </div>
        <div className="rounded-md border border-border bg-surface-muted/40 px-2.5 py-2">
          <p className="text-2xs text-muted-foreground">Used by</p>
          <p className="text-sm font-semibold tabular-nums">{incoming.length}</p>
        </div>
      </div>
      <div className="max-h-64 overflow-y-auto border-t border-border scrollbar-thin">
        {outgoing.length === 0 && incoming.length === 0 ? (
          <p className="px-4 py-4 text-center text-2xs text-muted-foreground">No resolved edges touch this node.</p>
        ) : (
          <ul className="divide-y divide-border/60">
            {[
              { label: "→ imports/calls", items: outgoing },
              { label: "← imported by", items: incoming },
            ].map((group) => (
              <li key={group.label} className="px-4 py-2">
                <p className="text-2xs uppercase tracking-wider text-muted-foreground">
                  {group.label} ({group.items.length})
                </p>
                <ul className="mt-1 space-y-0.5">
                  {group.items.slice(0, 20).map((edge) => (
                    <li key={`${group.label}-${edge.id}`} className="flex items-center gap-2 text-2xs">
                      <span className="mono truncate text-muted-foreground">
                        {group.label.startsWith("→") ? edge.target : edge.source}
                      </span>
                      <span className="ml-auto shrink-0 text-muted-foreground/60">{edge.kind}</span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
