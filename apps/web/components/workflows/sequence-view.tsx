"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, CircleChevronDown } from "lucide-react";
import type { Workflow } from "@/lib/types";
import { cn, basename } from "@/lib/utils";
import { PathLink } from "@/components/common/path-link";

const KIND_META: Record<string, { label: string; tone: string }> = {
  ui: { label: "UI", tone: "text-violet-300" },
  api: { label: "API", tone: "text-sky-300" },
  controller: { label: "handler", tone: "text-amber-300" },
  service: { label: "service", tone: "text-emerald-300" },
  repository: { label: "data", tone: "text-fuchsia-300" },
  database: { label: "database", tone: "text-orange-300" },
  auth: { label: "auth", tone: "text-rose-300" },
  external: { label: "external", tone: "text-slate-300" },
  util: { label: "util", tone: "text-slate-300" },
  background: { label: "background", tone: "text-cyan-300" },
};

function kindMeta(kind: string) {
  return KIND_META[kind] ?? { label: kind, tone: "text-muted-foreground" };
}

function layerForKind(kind: string): string {
  switch (kind) {
    case "ui":
      return "ui";
    case "api":
    case "controller":
      return "route";
    case "service":
      return "service";
    case "repository":
    case "database":
      return "repository";
    case "auth":
      return "middleware";
    default:
      return "other";
  }
}

const LAYER_TEXT: Record<string, string> = {
  ui: "text-violet-300",
  route: "text-sky-300",
  service: "text-emerald-300",
  repository: "text-fuchsia-300",
  middleware: "text-rose-300",
  other: "text-slate-300",
};

/**
 * Swimlane rendering of a traced workflow: one column per file involved, one row
 * per call step, arrows showing when control moves between files.
 */
export function SequenceView({ workflow }: { workflow: Workflow }) {
  const router = useRouter();

  const files = React.useMemo(() => {
    const ordered: string[] = [];
    workflow.steps.forEach((step) => {
      const path = step.file_path ?? "(unknown)";
      if (!ordered.includes(path)) ordered.push(path);
    });
    return ordered.slice(0, 8);
  }, [workflow]);

  const columnCount = Math.max(files.length, 1);
  const columnOf = (path: string | null | undefined) => Math.max(files.indexOf(path ?? "(unknown)"), 0);

  const open = (path: string, line?: number | null) =>
    router.push(`/explorer?path=${encodeURIComponent(path)}${line ? `&line=${line}` : ""}`);

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto pb-1 scrollbar-thin">
        <div className="flex min-w-full gap-2">
          {files.map((path) => {
            const step = workflow.steps.find((entry) => (entry.file_path ?? "(unknown)") === path);
            const layer = layerForKind(step?.kind ?? "other");
            return (
              <div key={path} className="min-w-[10.5rem] flex-1 rounded-lg border border-border bg-surface-muted/40 px-3 py-2">
                <p className={cn("text-2xs font-medium uppercase tracking-wider", LAYER_TEXT[layer] ?? "text-muted-foreground")}>
                  {layer === "route" ? "api" : layer}
                </p>
                <button
                  type="button"
                  onClick={() => open(path)}
                  className="mono mt-1 block w-full truncate text-left text-2xs transition-colors hover:text-primary"
                  title={path}
                >
                  {basename(path)}
                </button>
                <p className="truncate text-2xs text-muted-foreground/70">{path.split("/").slice(0, -1).join("/") || "."}</p>
              </div>
            );
          })}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface/60">
        <ol className="divide-y divide-border/50">
          {workflow.steps.map((step, index) => {
            const path = step.file_path ?? "(unknown)";
            const column = columnOf(path);
            const previous = index > 0 ? workflow.steps[index - 1] : null;
            const previousColumn = previous ? columnOf(previous.file_path) : 0;
            const direction = previous ? Math.sign(column - previousColumn) : 0;
            const meta = kindMeta(step.kind);

            return (
              <li key={step.id} className="px-3 py-2.5">
                {direction !== 0 ? (
                  <div className="mb-2 flex items-center gap-1.5 pl-1 text-2xs text-muted-foreground">
                    {direction > 0 ? <ArrowRight className="size-3 text-primary" /> : <ArrowLeft className="size-3 text-primary" />}
                    calls into <span className="mono">{basename(path)}</span>
                  </div>
                ) : null}

                <div className="overflow-x-auto scrollbar-thin">
                  <div className="flex min-w-full gap-2">
                    {files.map((file) => (
                      <div key={file} className="min-w-[10.5rem] flex-1">
                        {file === path ? (
                          <button
                            type="button"
                            onClick={() => step.file_path && open(step.file_path, step.line)}
                            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-left transition-colors hover:border-primary/50"
                          >
                            <span className="flex items-center gap-2">
                              <span
                                className={cn(
                                  "flex size-5 items-center justify-center rounded-full border border-border text-[0.625rem] font-semibold",
                                  meta.tone,
                                )}
                              >
                                {index + 1}
                              </span>
                              <span className={cn("text-2xs font-medium uppercase tracking-wider", meta.tone)}>{meta.label}</span>
                            </span>
                            <span className="mt-1 block text-xs font-medium leading-snug">{step.label}</span>
                            {step.symbol ? <span className="mono mt-0.5 block truncate text-2xs text-muted-foreground">{step.symbol}()</span> : null}
                            {step.detail ? <span className="mt-0.5 block text-2xs text-muted-foreground">{step.detail}</span> : null}
                          </button>
                        ) : (
                          <div className="h-full rounded-lg border border-dashed border-border/40" />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <CircleChevronDown className="size-3" /> Steps are ordered as the tracer walked the call graph.
        </span>
        {workflow.trace_truncated ? (
          <span className="text-amber-300">Trace truncated at the configured depth — deeper calls are not shown.</span>
        ) : null}
        {workflow.steps[0]?.file_path ? <PathLink path={workflow.steps[0].file_path} label="Open entry file" compact /> : null}
      </div>
    </div>
  );
}
