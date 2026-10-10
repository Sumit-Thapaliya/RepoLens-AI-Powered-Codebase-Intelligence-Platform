"use client";

import * as React from "react";
import { Database as DatabaseIcon, FileSpreadsheet, GitMerge, ListChecks, Search } from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { StatCard } from "@/components/common/kpi";
import { Erd } from "@/components/database/erd";
import { PathLink } from "@/components/common/path-link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, ErrorState, InlineNote, SkeletonCard } from "@/components/ui/states";
import { getDatabase } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { cn, formatNumber } from "@/lib/utils";

const QUERY_TONE: Record<string, string> = {
  select: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  insert: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  update: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  delete: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  raw: "border-violet-500/30 bg-violet-500/10 text-violet-300",
  unknown: "border-border bg-secondary text-muted-foreground",
};

function DatabaseBody() {
  const { analysisId } = useAnalysisContext();
  const [selectedModel, setSelectedModel] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");
  const [queryKind, setQueryKind] = React.useState<string | null>(null);
  const { data: payload, error, isLoading: loading, mutate } = useApi(
    analysisId ? `database:${analysisId}` : null,
    () => getDatabase(analysisId!),
  );
  const load = React.useCallback(async () => {
    await mutate();
  }, [mutate]);

  React.useEffect(() => {
    if (!payload) return;
    setSelectedModel((current) =>
      payload.models.some((model) => model.id === current) ? current : payload.models[0]?.id ?? null,
    );
  }, [payload]);

  const model = payload?.models.find((entry) => entry.id === selectedModel) ?? payload?.models[0] ?? null;
  const modelQueries = React.useMemo(
    () => (payload && model ? payload.queries.filter((entry) => entry.table === model.name || entry.table === model.table) : []),
    [payload, model],
  );

  const filteredQueries = React.useMemo(() => {
    if (!payload) return [];
    const needle = query.trim().toLowerCase();
    return payload.queries.filter((entry) => {
      if (queryKind && entry.kind !== queryKind) return false;
      if (!needle) return true;
      return (
        (entry.snippet ?? "").toLowerCase().includes(needle) ||
        (entry.table ?? "").toLowerCase().includes(needle) ||
        entry.file_path.toLowerCase().includes(needle)
      );
    });
  }, [payload, query, queryKind]);

  if (loading && !payload) {
    return (
      <div className="grid gap-4 p-4 lg:grid-cols-3 lg:p-6">
        {Array.from({ length: 4 }).map((_, index) => (
          <SkeletonCard key={index} lines={2} />
        ))}
        <SkeletonCard className="lg:col-span-3" lines={10} />
      </div>
    );
  }
  if (error && !payload) return <ErrorState error={error} onRetry={() => void load()} className="m-6" />;
  if (!payload) return null;

  const stats = payload.stats;
  const byKind = (stats.by_kind as Record<string, number>) ?? {};

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div>
        <h1 className="text-base font-semibold tracking-tight">Database</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Models, tables, queries and migrations detected in the source. Technologies come from manifests, config files
          and ORM imports.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard label="Models" value={Number(stats.models ?? 0)} hint="ORM model / table classes" icon={DatabaseIcon} tone="primary" />
        <StatCard label="Tables" value={Number(stats.tables ?? 0)} hint="Table names (explicit + derived)" />
        <StatCard label="Queries" value={Number(stats.queries ?? 0)} hint="Static query call sites" icon={ListChecks} />
        <StatCard label="Migrations" value={Number(stats.migrations ?? 0)} hint="Alembic / Prisma / SQL migration files" icon={GitMerge} />
        <StatCard label="Relations" value={Number(stats.relations ?? 0)} hint="Resolved FK / relationship fields" />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {payload.technologies.map((technology) => (
          <div key={technology.name} className="flex items-center gap-2 rounded-lg border border-border bg-surface-muted/50 px-2.5 py-1.5">
            <span className="text-xs font-medium">{technology.name}</span>
            <Badge variant="secondary">{technology.kind}</Badge>
            <Badge variant={technology.confidence >= 0.9 ? "success" : "warning"} className="mono">
              {(technology.confidence * 100).toFixed(0)}%
            </Badge>
          </div>
        ))}
        {payload.orms.length ? (
          <span className="text-2xs text-muted-foreground">ORMs / access styles: {payload.orms.join(", ")}</span>
        ) : null}
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <section className="panel overflow-hidden">
          <div className="panel-header">
            <span className="panel-title flex items-center gap-2">
              <GitMerge className="size-3.5 text-muted-foreground" /> Entity relationships
            </span>
            <span className="text-2xs text-muted-foreground">click a model to inspect it</span>
          </div>
          <Erd models={payload.models} relations={payload.relations} selectedId={selectedModel} onSelect={setSelectedModel} />
        </section>

        <div className="space-y-4">
          {model ? (
            <section className="panel overflow-hidden">
              <div className="panel-header">
                <div className="min-w-0">
                  <span className="panel-title block truncate">{model.name}</span>
                  <span className="mono mt-0.5 block text-2xs text-muted-foreground">
                    {model.table ? `table ${model.table}` : "table name not explicit"} · {model.orm ?? "unknown ORM"}
                  </span>
                </div>
                <PathLink path={model.file_path} line={model.line} label="source" compact />
              </div>
              <div className="max-h-72 overflow-y-auto scrollbar-thin">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border text-left text-2xs uppercase tracking-wider text-muted-foreground">
                      <th className="px-4 py-2 font-medium">Field</th>
                      <th className="px-2 py-2 font-medium">Type</th>
                      <th className="px-4 py-2 font-medium">Flags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {model.fields.map((field) => (
                      <tr key={field.name} className="border-b border-border/50 last:border-0">
                        <td className="mono px-4 py-1.5">{field.name}</td>
                        <td className="mono px-2 py-1.5 text-muted-foreground">{(field.type ?? "—").slice(0, 30)}</td>
                        <td className="px-4 py-1.5">
                          <span className="flex flex-wrap gap-1">
                            {field.primary_key ? <Badge variant="warning">PK</Badge> : null}
                            {field.foreign_key ? <Badge variant="info">FK</Badge> : null}
                            {field.nullable === false ? <Badge variant="outline">required</Badge> : null}
                            {field.unique ? <Badge variant="outline">unique</Badge> : null}
                            {field.on_delete ? <Badge variant="outline">on delete {field.on_delete}</Badge> : null}
                          </span>
                        </td>
                      </tr>
                    ))}
                    {model.fields.length === 0 ? (
                      <tr>
                        <td colSpan={3} className="px-4 py-4 text-center text-2xs text-muted-foreground">
                          Fields could not be read statically for this model.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
              {model.relationships.length ? (
                <div className="border-t border-border px-4 py-3">
                  <p className="text-2xs uppercase tracking-wider text-muted-foreground">Relationships</p>
                  <ul className="mt-1.5 space-y-1">
                    {model.relationships.map((relation, index) => (
                      <li key={index} className="text-2xs text-muted-foreground">
                        <span className="mono text-foreground/80">{relation.kind}</span> {relation.field ?? relation.name} →{" "}
                        <span className="mono">{relation.target ?? "unresolved"}</span>
                        {relation.target_field ? ` (${relation.target_field})` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <div className="border-t border-border p-4">
                <p className="text-2xs uppercase tracking-wider text-muted-foreground">
                  Queries touching this model ({modelQueries.length || model.query_count || 0})
                </p>
                <ul className="mt-1.5 space-y-1">
                  {(modelQueries.length ? modelQueries.slice(0, 4) : payload.queries.slice(0, 3)).map((entry) => (
                    <li key={entry.id} className="flex items-center justify-between gap-2">
                      <span className="mono truncate text-2xs text-muted-foreground" title={entry.snippet ?? undefined}>
                        {entry.snippet ?? entry.kind}
                      </span>
                      <PathLink path={entry.file_path} line={entry.line} compact showLine />
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          ) : (
            <EmptyState icon={DatabaseIcon} title="No models detected" detail="This repository may not use an ORM that RepoLens can read statically." />
          )}

          <section className="panel overflow-hidden">
            <div className="panel-header">
              <span className="panel-title flex items-center gap-2">
                <FileSpreadsheet className="size-3.5 text-muted-foreground" /> Migrations
              </span>
              <span className="text-2xs text-muted-foreground">{payload.migrations.length} files</span>
            </div>
            <ul className="max-h-56 divide-y divide-border overflow-y-auto scrollbar-thin">
              {payload.migrations.map((migration) => (
                <li key={migration.id} className="px-4 py-2.5">
                  <PathLink path={migration.path} label={migration.path.split("/").pop()} />
                  <p className="mt-1 text-2xs text-muted-foreground">
                    {migration.framework ?? "migration"} · {migration.operations} operations
                    {migration.tables.length ? ` · tables: ${migration.tables.slice(0, 4).join(", ")}` : ""}
                  </p>
                </li>
              ))}
              {payload.migrations.length === 0 ? (
                <li className="px-4 py-5 text-center text-2xs text-muted-foreground">No migration files found.</li>
              ) : null}
            </ul>
          </section>
        </div>
      </div>

      <section className="panel overflow-hidden">
        <div className="panel-header">
          <span className="panel-title">Queries</span>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter queries…"
                className="h-8 w-60 pl-8 text-xs"
              />
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 px-5 pt-3">
          <button
            type="button"
            onClick={() => setQueryKind(null)}
            className={cn(
              "rounded-md border px-2 py-0.5 text-2xs transition-colors",
              queryKind === null ? "border-primary/40 bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            all ({payload.queries.length})
          </button>
          {Object.entries(byKind)
            .sort((a, b) => b[1] - a[1])
            .map(([kind, count]) => (
              <button
                key={kind}
                type="button"
                onClick={() => setQueryKind(kind)}
                className={cn(
                  "rounded-md border px-2 py-0.5 text-2xs transition-colors",
                  queryKind === kind ? "border-primary/40 bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                {kind} ({count})
              </button>
            ))}
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left text-2xs uppercase tracking-wider text-muted-foreground">
                <th className="px-5 py-2 font-medium">Kind</th>
                <th className="px-3 py-2 font-medium">Snippet</th>
                <th className="px-3 py-2 font-medium">Table</th>
                <th className="px-3 py-2 font-medium">ORM</th>
                <th className="px-5 py-2 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {filteredQueries.slice(0, 60).map((entry) => (
                <tr key={entry.id} className="border-b border-border/50 last:border-0">
                  <td className="px-5 py-2">
                    <span className={cn("rounded border px-1.5 py-0.5 text-2xs", QUERY_TONE[entry.kind] ?? QUERY_TONE.unknown)}>
                      {entry.kind}
                    </span>
                  </td>
                  <td className="mono max-w-md truncate px-3 py-2 text-muted-foreground" title={entry.snippet ?? undefined}>
                    {entry.snippet ?? "—"}
                  </td>
                  <td className="mono px-3 py-2 text-muted-foreground">{entry.table ?? "—"}</td>
                  <td className="px-3 py-2 text-muted-foreground">{entry.orm ?? "—"}</td>
                  <td className="px-5 py-2">
                    <PathLink path={entry.file_path} line={entry.line} compact />
                  </td>
                </tr>
              ))}
              {filteredQueries.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-5 py-8 text-center text-muted-foreground">
                    No query matches this filter.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        {filteredQueries.length > 60 ? (
          <p className="border-t border-border px-5 py-2 text-2xs text-muted-foreground">
            Showing the first 60 of {formatNumber(filteredQueries.length)} matching queries.
          </p>
        ) : null}
      </section>

      <InlineNote>
        {payload.notes.join(" ")} Query extraction is intentionally conservative: a statement is only reported when it can
        be attributed to a concrete call site, so dynamic query builders may under-report.
      </InlineNote>
    </div>
  );
}

export default function DatabasePage() {
  return (
    <RunGate title="Analyse a repository to inspect its data layer">
      <DatabaseBody />
    </RunGate>
  );
}
