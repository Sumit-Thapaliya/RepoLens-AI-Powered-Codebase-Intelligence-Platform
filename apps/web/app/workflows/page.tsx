"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { GitBranch, ListTree, Lock, Search, Waypoints } from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { SequenceView } from "@/components/workflows/sequence-view";
import { PathLink } from "@/components/common/path-link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, ErrorState, InlineNote, SkeletonCard } from "@/components/ui/states";
import { getWorkflows } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Workflow } from "@/lib/types";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { cn, truncate } from "@/lib/utils";

const CATEGORY_TONE: Record<string, string> = {
  auth: "border-rose-500/30 bg-rose-500/10 text-rose-200",
  crud: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  notification: "border-sky-500/30 bg-sky-500/10 text-sky-200",
  registration: "border-violet-500/30 bg-violet-500/10 text-violet-200",
  payment: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  background: "border-cyan-500/30 bg-cyan-500/10 text-cyan-200",
};

function WorkflowsBody() {
  const { analysisId } = useAnalysisContext();
  const [category, setCategory] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [view, setView] = React.useState("steps");
  const router = useRouter();
  const { data: payload, error, isLoading: loading, mutate } = useApi(
    analysisId ? `workflows:${analysisId}:80` : null,
    () => getWorkflows(analysisId!, undefined, 80),
  );
  const load = React.useCallback(async () => {
    await mutate();
  }, [mutate]);

  React.useEffect(() => {
    if (!payload) return;
    setSelectedId((current) =>
      payload.workflows.some((workflow) => workflow.id === current)
        ? current
        : payload.workflows[0]?.id ?? null,
    );
  }, [payload]);

  const filtered = React.useMemo(() => {
    if (!payload) return [];
    const needle = query.trim().toLowerCase();
    return payload.workflows.filter((workflow) => {
      if (category && workflow.category !== category) return false;
      if (!needle) return true;
      return (
        workflow.name.toLowerCase().includes(needle) ||
        (workflow.trigger ?? "").toLowerCase().includes(needle) ||
        workflow.files.some((file) => file.toLowerCase().includes(needle))
      );
    });
  }, [payload, category, query]);

  const selected: Workflow | null = React.useMemo(
    () => filtered.find((workflow) => workflow.id === selectedId) ?? filtered[0] ?? null,
    [filtered, selectedId],
  );

  if (loading && !payload) {
    return (
      <div className="grid gap-4 p-4 lg:grid-cols-[22rem_minmax(0,1fr)] lg:p-6">
        <SkeletonCard lines={10} />
        <SkeletonCard lines={12} />
      </div>
    );
  }
  if (error && !payload) return <ErrorState error={error} onRetry={() => void load()} className="m-6" />;
  if (!payload) return null;
  const categoryFilters = new Map<
  string,
  { category: string; label: string; count: number }
  >();

  for (const entry of payload.categories) {
    const existing = categoryFilters.get(entry.category);
    categoryFilters.set(
      entry.category,
      existing
        ? { ...existing, count: existing.count + entry.count }
        : { ...entry },
    );
  }

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-base font-semibold tracking-tight">Workflows</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {payload.total} traced flows from entry points through handlers, services and data access. Detected from
            call-graph traversal, not declared anywhere in the source.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filter flows…"
              className="h-8 w-56 pl-8 text-xs"
            />
          </div>
          <Tabs value={view} onValueChange={setView}>
            <TabsList>
              <TabsTrigger value="steps">
                <ListTree className="size-3" /> Steps
              </TabsTrigger>
              <TabsTrigger value="sequence">
                <Waypoints className="size-3" /> Sequence
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={() => setCategory(null)}
          className={cn(
            "rounded-md border px-2.5 py-1 text-2xs transition-colors",
            category === null ? "border-primary/40 bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground",
          )}
        >
          All ({payload.workflows.length})
        </button>
        {Array.from(categoryFilters.values()).map((entry) => (
          <button
            key={entry.category}
            type="button"
            onClick={() => setCategory(entry.category)}
            className={cn(
              "rounded-md border px-2.5 py-1 text-2xs transition-colors",
              category === entry.category
                ? "border-primary/40 bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {entry.label} ({entry.count})
          </button>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <section className="panel flex max-h-[38rem] flex-col overflow-hidden">
          <div className="panel-header">
            <span className="panel-title flex items-center gap-2">
              <GitBranch className="size-3.5 text-muted-foreground" /> Detected flows
            </span>
            <span className="text-2xs text-muted-foreground">{filtered.length} shown</span>
          </div>
          <ul className="flex-1 divide-y divide-border overflow-y-auto scrollbar-thin">
            {filtered.length === 0 ? (
              <li className="p-6 text-center text-xs text-muted-foreground">
                {payload.workflows.length === 0
                  ? "No HTTP entry points to trace in this repository. Workflows are seeded from route declarations and HTTP handlers, so a library or CLI without routes legitimately has none."
                  : "No workflow matches this filter."}
              </li>
            ) : (
              filtered.map((workflow) => (
                <li key={workflow.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(workflow.id)}
                    className={cn(
                      "w-full px-4 py-3 text-left transition-colors",
                      selected?.id === workflow.id ? "bg-primary/5" : "hover:bg-secondary/40",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-xs font-medium">{workflow.name}</span>
                      <span className="shrink-0 text-2xs tabular-nums text-muted-foreground">
                        {(workflow.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <span
                        className={cn(
                          "rounded border px-1.5 py-0.5 text-2xs",
                          CATEGORY_TONE[workflow.category] ?? "border-border bg-secondary text-muted-foreground",
                        )}
                      >
                        {workflow.category_label ?? workflow.category}
                      </span>
                      {workflow.route?.method ? (
                        <Badge variant="outline" className="mono font-normal">
                          {workflow.route.method} {truncate(workflow.route.path ?? "", 22)}
                        </Badge>
                      ) : null}
                      {workflow.route?.auth_required ? (
                        <Badge variant="danger">
                          <Lock /> auth
                        </Badge>
                      ) : null}
                      {workflow.scope === "example" ? (
                        <Badge variant="outline" className="text-amber-200/90" title={workflow.scope_note ?? undefined}>
                          example app
                        </Badge>
                      ) : null}
                      {workflow.scope === "test" ? (
                        <Badge variant="outline" className="text-sky-200/90" title={workflow.scope_note ?? undefined}>
                          test app
                        </Badge>
                      ) : null}
                    </div>
                    <p className="mt-1 text-2xs text-muted-foreground">
                      {workflow.steps.length} steps · {workflow.files.length} files
                    </p>
                  </button>
                </li>
              ))
            )}
          </ul>
        </section>

        {selected ? (
          <section className="panel flex min-h-0 flex-col overflow-hidden">
            <div className="panel-header">
              <div className="min-w-0">
                <span className="panel-title block truncate">{selected.name}</span>
                <span className="mt-0.5 block text-2xs text-muted-foreground">
                  {selected.description || "Traced from the resolved call graph."}
                </span>
                {selected.scope_note ? (
                  <span className="mt-1 block text-2xs text-amber-200/80">{selected.scope_note}</span>
                ) : null}
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <Badge variant="secondary" className="mono">
                  confidence {(selected.confidence * 100).toFixed(0)}%
                </Badge>
                {selected.steps[0]?.file_path ? (
                  <Button
                    size="xs"
                    variant="outline"
                    onClick={() =>
                      router.push(
                        `/explorer?path=${encodeURIComponent(selected.steps[0].file_path ?? "")}${
                          selected.steps[0].line ? `&line=${selected.steps[0].line}` : ""
                        }`,
                      )
                    }
                  >
                    Open entry point
                  </Button>
                ) : null}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 scrollbar-thin">
              <div className="mb-3 grid gap-2 sm:grid-cols-3">
                <div className="rounded-lg border border-border bg-surface-muted/40 px-3 py-2">
                  <p className="text-2xs uppercase tracking-wider text-muted-foreground">Trigger</p>
                  <p className="mono mt-0.5 truncate text-xs">{selected.trigger ?? "unknown"}</p>
                </div>
                <div className="rounded-lg border border-border bg-surface-muted/40 px-3 py-2">
                  <p className="text-2xs uppercase tracking-wider text-muted-foreground">Framework</p>
                  <p className="mt-0.5 text-xs">{selected.framework ?? "detected from route decorators"}</p>
                </div>
                <div className="rounded-lg border border-border bg-surface-muted/40 px-3 py-2">
                  <p className="text-2xs uppercase tracking-wider text-muted-foreground">Files touched</p>
                  <p className="mt-0.5 text-xs">{selected.files.length}</p>
                </div>
              </div>

              <Tabs value={view} onValueChange={setView}>
                <TabsContent value="steps" className="mt-0">
                  <ol className="space-y-2">
                    {selected.steps.map((step, index) => (
                      <li key={step.id} className="flex gap-3">
                        <div className="flex flex-col items-center pt-1">
                          <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-border bg-surface text-2xs font-semibold">
                            {index + 1}
                          </span>
                          {index < selected.steps.length - 1 ? <span className="mt-1 w-px flex-1 bg-border" /> : null}
                        </div>
                        <div className="min-w-0 flex-1 rounded-lg border border-border bg-surface/70 px-3 py-2.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="outline" className="font-normal">
                              {step.kind}
                            </Badge>
                            <span className="text-xs font-medium">{step.label}</span>
                            {step.symbol ? <span className="mono text-2xs text-muted-foreground">{step.symbol}()</span> : null}
                          </div>
                          {step.detail ? <p className="mt-1 text-2xs text-muted-foreground">{step.detail}</p> : null}
                          {step.evidence ? <p className="mt-1 text-2xs text-muted-foreground/80">{step.evidence}</p> : null}
                          {step.file_path ? (
                            <div className="mt-1.5">
                              <PathLink path={step.file_path} line={step.line} />
                            </div>
                          ) : null}
                        </div>
                      </li>
                    ))}
                  </ol>
                </TabsContent>
                <TabsContent value="sequence" className="mt-0">
                  <SequenceView workflow={selected} />
                </TabsContent>
              </Tabs>

              {selected.evidence?.length ? (
                <div className="mt-4">
                  <p className="text-2xs uppercase tracking-wider text-muted-foreground">Evidence</p>
                  <ul className="mt-1.5 space-y-1">
                    {selected.evidence.map((item, index) => (
                      <li key={index} className="text-2xs text-muted-foreground">
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <InlineNote className="mt-4">
                Workflows are traced by following resolved calls from entry points (routes, handlers, event hooks) up to
                a configurable depth. A flow being absent means the tracer did not see a resolvable call chain — it does
                not prove the code path does not exist.
              </InlineNote>
            </div>
          </section>
        ) : (
          <EmptyState
            icon={GitBranch}
            title="No workflow selected"
            detail="Choose a flow on the left, or broaden the filter. Workflows are only produced when the tracer finds resolvable calls from an entry point."
          />
        )}
      </div>
    </div>
  );
}

export default function WorkflowsPage() {
  return (
    <RunGate title="Analyse a repository to trace its workflows">
      <WorkflowsBody />
    </RunGate>
  );
}
