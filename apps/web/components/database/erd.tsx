"use client";

import * as React from "react";
import type { DbModel } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Box {
  model: DbModel;
  x: number;
  y: number;
  w: number;
  h: number;
}

const BOX_W = 210;
const HEADER_H = 30;
const ROW_H = 15;
const MAX_ROWS = 9;
const GAP_X = 60;
const GAP_Y = 40;

/**
 * Entity-relationship rendering of the detected models. Edges are drawn only for
 * relations the analysis actually resolved (foreign keys / relationship fields) —
 * nothing is inferred from naming.
 */
export function Erd({
  models,
  relations,
  selectedId,
  onSelect,
}: {
  models: DbModel[];
  relations: { source: string; target: string; kind: string; field?: string | null; resolved: boolean }[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { boxes, width, height } = React.useMemo(() => {
    const perColumn = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(models.length || 1))));
    const placed: Box[] = models.map((model, index) => {
      const column = Math.floor(index / perColumn);
      const row = index % perColumn;
      const rows = Math.min(model.fields.length, MAX_ROWS);
      const boxHeight = HEADER_H + rows * ROW_H + (model.fields.length > MAX_ROWS ? ROW_H : 0) + 8;
      return { model, x: column * (BOX_W + GAP_X), y: row * 0, h: boxHeight, w: BOX_W };
    });
    // stack within columns, keeping a running y per column
    const columnY = new Map<number, number>();
    placed.forEach((box, index) => {
      const column = Math.floor(index / perColumn);
      const y = columnY.get(column) ?? 0;
      box.y = y;
      columnY.set(column, y + box.h + GAP_Y);
    });
    const maxX = Math.max(...placed.map((box) => box.x + box.w), BOX_W);
    const maxY = Math.max(...placed.map((box) => box.y + box.h), 300);
    return { boxes: placed, width: maxX + 20, height: maxY + 20 };
  }, [models]);

  const byName = React.useMemo(() => {
    const map = new Map<string, Box>();
    boxes.forEach((box) => {
      map.set(box.model.name, box);
      if (box.model.table) map.set(box.model.table, box);
    });
    return map;
  }, [boxes]);

  if (!models.length) {
    return (
      <p className="p-10 text-center text-xs text-muted-foreground">
        No ORM models or table definitions were detected in this repository.
      </p>
    );
  }

  return (
    <div className="overflow-auto p-4 scrollbar-thin">
      <svg width={width} height={height} className="min-w-full">
        <defs>
          <marker id="erd-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
          </marker>
        </defs>

        {relations.map((relation, index) => {
          const from = byName.get(relation.source);
          const to = byName.get(relation.target);
          if (!from || !to) return null;
          const x1 = from.x + from.w;
          const y1 = from.y + HEADER_H / 2;
          const x2 = to.x;
          const y2 = to.y + HEADER_H / 2;
          const midX = (x1 + x2) / 2;
          return (
            <g key={index}>
              <path
                d={`M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`}
                fill="none"
                stroke="#475569"
                strokeDasharray={relation.resolved ? undefined : "4 3"}
                strokeWidth={1.4}
                markerEnd="url(#erd-arrow)"
              />
              {relation.field ? (
                <text x={midX} y={(y1 + y2) / 2 - 4} textAnchor="middle" fontSize="9" fill="#94a3b8">
                  {relation.field}
                </text>
              ) : null}
            </g>
          );
        })}

        {boxes.map((box) => {
          const active = box.model.id === selectedId;
          const shown = box.model.fields.slice(0, MAX_ROWS);
          return (
            <g key={box.model.id} onClick={() => onSelect(box.model.id)} className="cursor-pointer">
              <rect
                x={box.x}
                y={box.y}
                width={box.w}
                height={box.h}
                rx={10}
                fill={active ? "#141b2b" : "#0f1319"}
                stroke={active ? "#22d3ee" : "#232a36"}
                strokeWidth={active ? 1.6 : 1}
              />
              <rect x={box.x} y={box.y} width={box.w} height={HEADER_H} rx={10} fill={active ? "#0e2233" : "#151a22"} />
              <text x={box.x + 12} y={box.y + 19} fontSize="12" fontWeight="600" fill={active ? "#67e8f9" : "#e2e8f0"}>
                {box.model.name}
              </text>
              <text x={box.x + box.w - 12} y={box.y + 19} fontSize="9" textAnchor="end" fill="#7c8798">
                {box.model.table ?? box.model.orm ?? ""}
              </text>

              {shown.map((field, index) => (
                <g key={field.name}>
                  <text x={box.x + 12} y={box.y + HEADER_H + 12 + index * ROW_H} fontSize="10" fill={field.primary_key ? "#fbbf24" : "#cbd5e1"}>
                    {field.primary_key ? "PK " : field.foreign_key ? "FK " : "   "}
                    {field.name}
                  </text>
                  <text x={box.x + box.w - 12} y={box.y + HEADER_H + 12 + index * ROW_H} fontSize="9.5" textAnchor="end" fill="#7c8798">
                    {(field.type ?? "").slice(0, 22)}
                  </text>
                </g>
              ))}
              {box.model.fields.length > MAX_ROWS ? (
                <text x={box.x + 12} y={box.y + HEADER_H + 12 + MAX_ROWS * ROW_H} fontSize="9.5" fill="#7c8798">
                  +{box.model.fields.length - MAX_ROWS} more fields…
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>

      {relations.length === 0 ? (
        <p className={cn("mt-1 rounded-md border border-border bg-surface-muted/40 px-3 py-2 text-2xs text-muted-foreground")}>
          No explicit relations could be resolved between models — RepoLens only draws edges that appear as relationship
          fields or foreign keys in the source, so this diagram shows the schema without inventing join paths.
        </p>
      ) : null}
    </div>
  );
}
