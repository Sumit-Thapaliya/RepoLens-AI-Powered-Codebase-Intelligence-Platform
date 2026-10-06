"use client";

import * as React from "react";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeftRight, ArrowRight, FlaskConical, GitBranch, ShieldAlert, Sparkles, Workflow as WorkflowIcon } from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { PathLink } from "@/components/common/path-link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, InlineNote, SkeletonCard, useToast } from "@/components/ui/states";
import { ApiError, getFileTree, getImpact } from "@/lib/api";
import type { FileNode, ImpactFile, ImpactReport } from "@/lib/types";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { cn, formatNumber, layerLabel, severityColor } from "@/lib/utils";

function flatten(node: FileNode, out: string[] = []): string[] {
  if (node.type === "file") out.push(node.path);
  (node.children ?? []).forEach((child) => flatten(child, out));
  return out;
}

function FilePicker({
  paths,
  value,
  onChange,
  placeholder = "Search files by path…",
}: {
  paths: string[];
  value: string;
  onChange: (path: string) => void;
  placeholder?: string;
}) {
  const [query, setQuery] = React.useState(value);
  const [open, setOpen] = React.useState(false);
  const matches = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return paths.slice(0, 12);
    return paths.filter((path) => path.toLowerCase().includes(needle)).slice(0, 30);
  }, [paths, query]);

  return (
    <div className="relative">
      <Input
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={placeholder}
        className="mono h-9 text-xs"
      />
      {open && matches.length ? (
        <div className="absolute z-30 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border border-border bg-popover p-1 shadow-xl scrollbar-thin">
          {matches.map((path) => (
            <button
              key={path}
              type="button"
              className="mono block w-full truncate rounded-md px-2 py-1 text-left text-2xs transition-colors hover:bg-secondary/70"
              onMouseDown={(event) => {
                event.preventDefault();
                onChange(path);
                setQuery(path);
                setOpen(false);
              }}
            >
              {path}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function FileList({ items, empty, onOpen, note }: { items: (ImpactFile | (ImpactFile & { distance: number; via: string }))[]; empty: string; onOpen: (path: string) => void; note?: string }) {
  if (!items.length) return <p className="px-4 py-4 text-center text-2xs text-muted-foreground">{empty}</p>;
  return (
    <ul className="divide-y divide-border/60">
      {items.slice(0, 14).map((item) => (
        <li key={`${item.path}-${(item as { distance?: number }).distance ?? 0}`} className="flex items-center justify-between gap-2 px-4 py-2">
          <button type="button" className="min-w-0 text-left" onClick={() => onOpen(item.path)}>
            <span className="mono block truncate text-2xs" title={item.path}>
              {item.path}
            </span>
            <span className="text-2xs text-muted-foreground">
              {item.layer ? layerLabel(item.layer) : "file"}
              {item.is_test ? " · test" : ""}
              {(item as { via?: string }).via ? ` · via ${(item as { via: string }).via}` : ""}
              {note ? ` · ${note}` : ""}
            </span>
          </button>
          <span className="shrink-0 text-2xs tabular-nums text-muted-foreground">{item.fan_in ?? 0} in</span>
        </li>
      ))}
    </ul>
  );
}

function ImpactBody() {
  const { analysisId } = useAnalysisContext();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { push } = useToast();

  const [paths, setPaths] = React.useState<string[]>([]);
  const [path, setPath] = React.useState(searchParams.get("path") ?? "");
  const [symbol, setSymbol] = React.useState(searchParams.get("symbol") ?? "");
  const [depth, setDepth] = React.useState(3);
  const [report, setReport] = React.useState<ImpactReport | null>(null);
  const [error, setError] = React.useState<ApiError | null>(null);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!analysisId) return;
    getFileTree(analysisId)
      .then((payload) => setPaths(flatten(payload.root).sort()))
      .catch(() => setPaths([]));
  }, [analysisId]);

  const run = React.useCallback(
    async (targetPath: string, targetSymbol?: string | null) => {
      if (!analysisId || !targetPath) return;
      setLoading(true);
      setError(null);
      try {
        const payload = await getImpact(analysisId, targetPath, targetSymbol ?? null, depth);
        if (payload.error) {
          setReport(null);
          push({ tone: "error", title: "Impact unavailable", detail: payload.error });
        } else {
          setReport(payload);
        }
      } catch (cause) {
        const apiError = cause instanceof ApiError ? cause : new ApiError(String(cause));
        setError(apiError);
        setReport(null);
      } finally {
        setLoading(false);
      }
    },
    [analysisId, depth, push],
  );

  React.useEffect(() => {
    if (searchParams.get("path")) void run(searchParams.get("path") as string, searchParams.get("symbol"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId]);

  const openFile = (target: string, line?: number | null) =>
    router.push(`/explorer?path=${encodeURIComponent(target)}${line ? `&line=${line}` : ""}`);

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div>
        <h1 className="text-base font-semibold tracking-tight">Impact analysis</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          What depends on a file, which endpoints and workflows pass through it, which tests cover it, and how risky a
          change is. Computed on the stored graph — no re-analysis needed.
        </p>
      </div>

      <section className="panel p-4">
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_14rem_10rem_auto]">
          <FilePicker paths={paths} value={path} onChange={(value) => setPath(value)} />
          <Input
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            placeholder="Symbol (optional)"
            className="mono h-9 text-xs"
          />
          <div className="flex items-center gap-2">
            <label className="whitespace-nowrap text-2xs text-muted-foreground" htmlFor="depth">
              depth {depth}
            </label>
            <input
              id="depth"
              type="range"
              min={1}
              max={5}
              value={depth}
              onChange={(event) => setDepth(Number(event.target.value))}
              className="w-full accent-[hsl(var(--primary))]"
            />
          </div>
          <Button loading={loading} disabled={!path} onClick={() => void run(path, symbol || null)}>
            Analyse impact
          </Button>
        </div>
        <p className="mt-2 text-2xs text-muted-foreground">
          {paths.length} files indexed for this run. Tip: start from the Code Explorer or the Dependencies graph to land
          here with a file already chosen.
        </p>
      </section>

      {error ? <ErrorState error={error} onRetry={() => void run(path, symbol || null)} className="" /> : null}

      {loading && !report ? (
        <div className="grid gap-4 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <SkeletonCard key={index} lines={5} />
          ))}
        </div>
      ) : null}

      {report ? (
        <>
          <section className="panel p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="mono text-sm">{report.target.path}</p>
                <p className="mt-1 text-2xs text-muted-foreground">
                  {report.target.layer ? layerLabel(report.target.layer) : "file"} · {report.target.loc ?? 0} loc
                  {report.target.symbol ? ` · symbol ${report.target.symbol}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button size="xs" variant="outline" onClick={() => openFile(report.target.path)}>
                  Open in explorer
                </Button>
                <Button size="xs" variant="outline" onClick={() => router.push(`/chat?path=${encodeURIComponent(report.target.path)}`)}>
                  <Sparkles className="size-3" /> Ask about this file
                </Button>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
              {[
                { label: "Direct dependencies", value: report.direct_dependencies.length, hint: "imports/calls out" },
                { label: "Dependents", value: report.dependents.length, hint: "files importing this" },
                { label: "Transitive dependents", value: report.indirect_dependents.length, hint: `up to depth ${depth}` },
                { label: "Affected endpoints", value: report.affected_endpoints.length, hint: "routes in the blast radius" },
                { label: "Related tests", value: report.related_tests.length, hint: "tests that import it" },
              ].map((stat) => (
                <div key={stat.label} className="rounded-lg border border-border bg-surface-muted/40 px-3 py-2.5">
                  <p className="text-2xs text-muted-foreground">{stat.label}</p>
                  <p className="mt-0.5 text-xl font-semibold tabular-nums">{formatNumber(stat.value)}</p>
                  <p className="text-2xs text-muted-foreground/80">{stat.hint}</p>
                </div>
              ))}
            </div>
            {report.risks.length ? (
              <div className="mt-4 space-y-2">
                {report.risks.map((risk, index) => (
                  <div key={index} className={cn("rounded-lg border px-3 py-2", severityColor(risk.level))}>
                    <p className="text-xs font-medium">
                      {risk.level.toUpperCase()} · {risk.title}
                      {risk.heuristic ? <span className="ml-2 text-2xs opacity-80">(heuristic)</span> : null}
                    </p>
                    <p className="mt-0.5 text-2xs opacity-90">{risk.detail}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </section>

          <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
            <section className="panel overflow-hidden">
              <div className="panel-header">
                <span className="panel-title flex items-center gap-2">
                  <ArrowRight className="size-3.5 text-emerald-300" /> Direct dependencies
                </span>
                <Badge variant="secondary">{report.direct_dependencies.length}</Badge>
              </div>
              <FileList items={report.direct_dependencies} empty="This file imports nothing that resolved." onOpen={openFile} />
            </section>

            <section className="panel overflow-hidden">
              <div className="panel-header">
                <span className="panel-title flex items-center gap-2">
                  <ArrowLeftRight className="size-3.5 text-sky-300" /> Dependents
                </span>
                <Badge variant="secondary">{report.dependents.length}</Badge>
              </div>
              <FileList items={report.dependents} empty="Nothing imports this file directly." onOpen={openFile} />
            </section>

            <section className="panel overflow-hidden">
              <div className="panel-header">
                <span className="panel-title flex items-center gap-2">
                  <GitBranch className="size-3.5 text-violet-300" /> Transitive dependents
                </span>
                <Badge variant="secondary">{report.indirect_dependents.length}</Badge>
              </div>
              <FileList items={report.indirect_dependents} empty="No indirect dependents within the depth limit." onOpen={openFile} />
            </section>

            <section className="panel overflow-hidden">
              <div className="panel-header">
                <span className="panel-title flex items-center gap-2">
                  <FlaskConical className="size-3.5 text-emerald-300" /> Related tests
                </span>
                <Badge variant="secondary">{report.related_tests.length}</Badge>
              </div>
              {report.related_tests.length ? (
                <ul className="divide-y divide-border/60">
                  {report.related_tests.slice(0, 14).map((test) => (
                    <li key={test.path} className="px-4 py-2">
                      <button type="button" className="w-full text-left" onClick={() => openFile(test.path)}>
                        <span className="mono block truncate text-2xs">{test.path}</span>
                        <span className="text-2xs text-muted-foreground">{test.reason}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="px-4 py-4 text-center text-2xs text-muted-foreground">
                  No test file imports this file. Consider adding one before changing it.
                </p>
              )}
            </section>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="panel overflow-hidden">
              <div className="panel-header">
                <span className="panel-title">Affected API endpoints</span>
                <Badge variant="secondary">{report.affected_endpoints.length}</Badge>
              </div>
              {report.affected_endpoints.length ? (
                <ul className="divide-y divide-border/60">
                  {report.affected_endpoints.slice(0, 12).map((endpoint) => (
                    <li key={endpoint.id} className="flex items-center justify-between gap-3 px-4 py-2">
                      <span className="mono min-w-0 truncate text-2xs">
                        <span className="text-foreground/90">{endpoint.method}</span> {endpoint.path}
                      </span>
                      <span className="flex shrink-0 items-center gap-2">
                        {endpoint.auth_required ? <Badge variant="danger">auth</Badge> : null}
                        <PathLink path={endpoint.file_path} line={endpoint.line} compact />
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="px-4 py-4 text-center text-2xs text-muted-foreground">No endpoint reaches this file.</p>
              )}
            </section>

            <section className="panel overflow-hidden">
              <div className="panel-header">
                <span className="panel-title flex items-center gap-2">
                  <WorkflowIcon className="size-3.5 text-amber-300" /> Affected workflows
                </span>
                <Badge variant="secondary">{report.affected_workflows.length}</Badge>
              </div>
              {report.affected_workflows.length ? (
                <ul className="divide-y divide-border/60">
                  {report.affected_workflows.slice(0, 10).map((workflow) => (
                    <li key={workflow.id} className="px-4 py-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-xs font-medium">{workflow.name}</span>
                        <Badge variant="outline">{(workflow.confidence * 100).toFixed(0)}%</Badge>
                      </div>
                      <p className="mt-0.5 text-2xs text-muted-foreground">
                        {workflow.category} · {workflow.impacted_steps.length} impacted step(s)
                        {workflow.impacted_steps[0] ? `: ${workflow.impacted_steps[0].label}` : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="px-4 py-4 text-center text-2xs text-muted-foreground">
                  No traced workflow passes through this file.
                </p>
              )}
            </section>
          </div>

          {report.notes?.length ? <InlineNote>{report.notes.join(" ")}</InlineNote> : null}
        </>
      ) : !loading && !error ? (
        <EmptyState
          icon={ShieldAlert}
          title="Pick a file to analyse"
          detail="Search for a file above (or open one from the Code Explorer) and RepoLens will compute its blast radius from the stored dependency graph and workflow traces."
        />
      ) : null}
    </div>
  );
}

export default function ImpactPage() {
  return (
    <RunGate title="Analyse a repository to run impact analysis">
      <Suspense fallback={<SkeletonCard className="m-6" lines={8} />}>
        <ImpactBody />
      </Suspense>
    </RunGate>
  );
}
