"use client";

import * as React from "react";
import { ArrowDownRight, CircleChevronDown, Workflow } from "lucide-react";
import type { Workflow as WorkflowData } from "@/lib/types";
import { basename, cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
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

/** Compact, ordered call-chain timeline for a traced workflow. */
export function SequenceView({ workflow }: { workflow: WorkflowData }) {
  const files = React.useMemo(
    () => new Set(workflow.steps.map((step) => step.file_path).filter((path): path is string => Boolean(path))),
    [workflow.steps],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/80 bg-gradient-to-br from-surface-raised/70 to-surface/40 px-3.5 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
            <Workflow className="size-4" />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-semibold">Call sequence</p>
            <p className="truncate text-2xs text-muted-foreground">Execution order from entry point through resolved calls</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Badge variant="secondary">{workflow.steps.length} steps</Badge>
          <Badge variant="outline">{files.size} files</Badge>
        </div>
      </div>

      <div className="relative">
        <div aria-hidden="true" className="absolute bottom-5 left-[13px] top-5 w-px bg-gradient-to-b from-primary/50 via-border to-transparent" />
        <ol className="relative space-y-2.5">
          {workflow.steps.map((step, index) => {
            const previous = index > 0 ? workflow.steps[index - 1] : null;
            const meta = kindMeta(step.kind);
            const fileChanged = Boolean(previous?.file_path && step.file_path && previous.file_path !== step.file_path);

            return (
              <li key={step.id} className="flex gap-3">
                <span
                  className={cn(
                    "z-10 flex size-7 shrink-0 items-center justify-center rounded-full border text-2xs font-semibold tabular-nums shadow-sm",
                    index === 0
                      ? "border-primary/40 bg-primary/15 text-primary"
                      : "border-border bg-surface-raised text-muted-foreground",
                  )}
                >
                  {index + 1}
                </span>

                <div className="min-w-0 flex-1 rounded-xl border border-border/80 bg-surface/65 px-3.5 py-3 transition-colors hover:border-primary/30">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className={cn("font-medium", meta.tone)}>
                      {meta.label}
                    </Badge>
                    {step.symbol ? <span className="mono truncate text-2xs text-muted-foreground">{step.symbol}()</span> : null}
                    {fileChanged && previous?.file_path ? (
                      <span className="ml-auto inline-flex items-center gap-1 text-2xs text-muted-foreground">
                        <ArrowDownRight className="size-3 text-primary" /> from {basename(previous.file_path)}
                      </span>
                    ) : null}
                  </div>

                  <p className="mt-1.5 text-xs font-medium leading-snug">{step.label}</p>
                  {step.detail ? <p className="mt-1 text-2xs leading-relaxed text-muted-foreground">{step.detail}</p> : null}
                  {step.evidence && step.evidence !== step.detail ? (
                    <p className="mt-1 line-clamp-2 text-2xs leading-relaxed text-muted-foreground/75">{step.evidence}</p>
                  ) : null}

                  {step.file_path ? (
                    <div className="mt-2">
                      <PathLink path={step.file_path} line={step.line} compact />
                    </div>
                  ) : (
                    <span className="mt-2 block text-2xs text-muted-foreground/60">Source file not resolved</span>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <CircleChevronDown className="size-3" /> Steps follow the order the tracer walked the call graph.
        </span>
        {workflow.trace_truncated ? (
          <span className="text-amber-300">Trace truncated at the configured depth — deeper calls are not shown.</span>
        ) : null}
      </div>
    </div>
  );
}
