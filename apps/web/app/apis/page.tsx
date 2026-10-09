"use client";

import * as React from "react";
import { Check, Copy, Download, Lock, Route, Search, ShieldQuestion, Unlock } from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { StatCard } from "@/components/common/kpi";
import { PathLink } from "@/components/common/path-link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorState, InlineNote, SkeletonCard, useToast } from "@/components/ui/states";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/menus";
import { ApiError, getApis } from "@/lib/api";
import type { Endpoint, EndpointPayload } from "@/lib/types";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { cn, formatNumber, methodColor } from "@/lib/utils";
import { downloadFile } from "@/lib/download";

function ApiBody() {
  const { analysisId } = useAnalysisContext();
  const { push } = useToast();
  const [payload, setPayload] = React.useState<EndpointPayload | null>(null);
  const [error, setError] = React.useState<ApiError | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [method, setMethod] = React.useState("all");
  const [auth, setAuth] = React.useState("all");
  const [source, setSource] = React.useState("all");
  const [query, setQuery] = React.useState("");
  const [copied, setCopied] = React.useState<string | null>(null);
  const [expanded, setExpanded] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    if (!analysisId) return;
    setLoading(true);
    setError(null);
    try {
      setPayload(await getApis(analysisId));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause : new ApiError(String(cause)));
    } finally {
      setLoading(false);
    }
  }, [analysisId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const endpoints = React.useMemo(() => {
    if (!payload) return [];
    const needle = query.trim().toLowerCase();
    return payload.endpoints.filter((endpoint) => {
      if (method !== "all" && endpoint.method !== method) return false;
      if (auth === "required" && !endpoint.auth_required) return false;
      if (auth === "public" && endpoint.auth_required) return false;
      if (source === "application" && (endpoint.is_example || endpoint.is_test)) return false;
      if (source === "examples" && !endpoint.is_example && !endpoint.is_test) return false;
      if (!needle) return true;
      return (
        endpoint.path.toLowerCase().includes(needle) ||
        (endpoint.handler ?? "").toLowerCase().includes(needle) ||
        (endpoint.service ?? "").toLowerCase().includes(needle) ||
        (endpoint.controller ?? "").toLowerCase().includes(needle) ||
        endpoint.file_path.toLowerCase().includes(needle)
      );
    });
  }, [payload, method, auth, source, query]);

  const methods = React.useMemo(() => {
    const counts = new Map<string, number>();
    payload?.endpoints.forEach((endpoint) => counts.set(endpoint.method, (counts.get(endpoint.method) ?? 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [payload]);

  const copyEndpoint = async (endpoint: Endpoint) => {
    const text = `${endpoint.method} ${endpoint.path}  →  ${endpoint.file_path}:${endpoint.line ?? 0}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(endpoint.id);
      setTimeout(() => setCopied(null), 1600);
    } catch {
      push({ tone: "error", title: "Clipboard unavailable", detail: "Your browser blocked clipboard access." });
    }
  };

  const exportMarkdown = () => {
    if (!payload) return;
    const lines = [
      `# API surface`,
      "",
      `| Method | Path | Handler | Service | Auth | Origin | Source |`,
      `| --- | --- | --- | --- | --- | --- | --- |`,
      ...payload.endpoints.map((endpoint) => {
        const origin = endpoint.is_example ? "example" : endpoint.is_test ? "test" : "application";
        const extra = (endpoint.declarations?.length ?? 1) > 1 ? ` (+${(endpoint.declarations?.length ?? 1) - 1} more)` : "";
        return `| ${endpoint.method} | \`${endpoint.path}\` | ${endpoint.handler ?? "—"} | ${endpoint.service ?? "—"} | ${endpoint.auth_required ? "yes" : "no"} | ${origin} | \`${endpoint.file_path}:${endpoint.line ?? 0}\`${extra} |`;
      }),
      "",
    ];
    downloadFile(`repolens-api-surface-${analysisId}.md`, lines.join("\n"), "text/markdown");
  };

  if (loading && !payload) {
    return (
      <div className="grid gap-4 p-4 lg:grid-cols-3 lg:p-6">
        {Array.from({ length: 3 }).map((_, index) => (
          <SkeletonCard key={index} lines={2} />
        ))}
        <SkeletonCard className="lg:col-span-3" lines={10} />
      </div>
    );
  }
  if (error && !payload) return <ErrorState error={error} onRetry={() => void load()} className="m-6" />;
  if (!payload) return null;

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-base font-semibold tracking-tight">API surface</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Every route declaration found in the parsed source, with the handler, the service it delegates to and the
            file it lives in.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={exportMarkdown}>
          <Download /> Export as Markdown
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Endpoints" value={payload.stats.total} hint="Distinct route declarations" icon={Route} tone="primary" />
        <StatCard label="Unique paths" value={payload.stats.unique_paths} hint="Paths after prefix reconstruction" />
        <StatCard
          label="Authenticated"
          value={payload.stats.authenticated}
          hint="Detected from dependencies, guards or decorators"
          icon={Lock}
        />
        <StatCard
          label="Public / unknown"
          value={payload.stats.total - payload.stats.authenticated}
          hint="No auth marker found on the handler"
          icon={Unlock}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter by path, handler, service…"
            className="h-8 w-72 pl-8 text-xs"
          />
        </div>
        <Select value={method} onValueChange={setMethod}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="Method" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All methods</SelectItem>
            {methods.map(([name, count]) => (
              <SelectItem key={name} value={name}>
                {name} ({count})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={auth} onValueChange={setAuth}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Auth" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Auth: any</SelectItem>
            <SelectItem value="required">Auth required</SelectItem>
            <SelectItem value="public">No auth marker</SelectItem>
          </SelectContent>
        </Select>
        <Select value={source} onValueChange={setSource}>
          <SelectTrigger className="w-48">
            <SelectValue placeholder="Source" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              Source: everything ({(payload.stats.from_examples ?? 0) + (payload.stats.from_tests ?? 0)} from examples/tests)
            </SelectItem>
            <SelectItem value="application">Source: application only</SelectItem>
            <SelectItem value="examples">Source: examples &amp; tests</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-2xs text-muted-foreground">
          {endpoints.length} of {payload.endpoints.length} shown
          {payload.frameworks.length ? ` · frameworks: ${payload.frameworks.map((f) => `${f.framework} (${f.count})`).join(", ")}` : ""}
        </span>
      </div>

      <section className="panel overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left text-2xs uppercase tracking-wider text-muted-foreground">
                <th className="px-5 py-2 font-medium">Method</th>
                <th className="px-3 py-2 font-medium">Endpoint</th>
                <th className="px-3 py-2 font-medium">Handler</th>
                <th className="px-3 py-2 font-medium">Controller</th>
                <th className="px-3 py-2 font-medium">Service</th>
                <th className="px-3 py-2 font-medium">Auth</th>
                <th className="px-3 py-2 font-medium">Source</th>
                <th className="px-5 py-2" />
              </tr>
            </thead>
            <tbody>
              {endpoints.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-5 py-10 text-center text-muted-foreground">
                    {payload.endpoints.length === 0
                      ? "No HTTP endpoints were found in this repository. That is expected for a library, CLI or data project - the parser only reports route declarations it actually found."
                      : "No endpoint matches the current filters."}
                  </td>
                </tr>
              ) : (
                endpoints.map((endpoint) => (
                  <React.Fragment key={endpoint.id}>
                    <tr className="border-b border-border/60 transition-colors last:border-0 hover:bg-secondary/30">
                      <td className="px-5 py-2.5">
                        <span className={cn("rounded border px-1.5 py-0.5 font-mono text-2xs font-semibold", methodColor(endpoint.method))}>
                          {endpoint.method}
                        </span>
                      </td>
                      <td className="mono px-3 py-2.5">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <button type="button" className="text-left hover:text-primary" onClick={() => setExpanded(endpoint.id)}>
                            {endpoint.path}
                          </button>
                          {endpoint.is_example ? (
                            <Badge variant="outline" className="text-amber-200/90" title="Primary declaration lives in an examples/ folder">
                              example
                            </Badge>
                          ) : null}
                          {endpoint.is_test ? (
                            <Badge variant="outline" className="text-sky-200/90" title="Primary declaration lives in a test app">
                              test
                            </Badge>
                          ) : null}
                          {(endpoint.declarations?.length ?? 1) > 1 ? (
                            <Badge variant="outline" className="text-muted-foreground" title="The same method and path is declared in several files">
                              ×{endpoint.declarations?.length}
                            </Badge>
                          ) : null}
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="mono text-muted-foreground">{endpoint.handler ?? "—"}</span>
                      </td>
                      <td className="px-3 py-2.5 text-muted-foreground">{endpoint.controller ?? "—"}</td>
                      <td className="px-3 py-2.5">
                        {endpoint.service ? (
                          <span className="mono text-emerald-200/90">{endpoint.service}</span>
                        ) : (
                          <span className="text-2xs text-muted-foreground/70" title="No resolvable call into a service/repository layer">
                            inline
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        {endpoint.auth_required ? (
                          <Badge variant="danger">
                            <Lock /> yes
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-muted-foreground">
                            none found
                          </Badge>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <PathLink path={endpoint.file_path} line={endpoint.line} compact />
                      </td>
                      <td className="px-5 py-2.5">
                        <Button size="icon-sm" variant="ghost" title="Copy endpoint" onClick={() => void copyEndpoint(endpoint)}>
                          {copied === endpoint.id ? <Check className="text-emerald-400" /> : <Copy />}
                        </Button>
                      </td>
                    </tr>
                    {expanded === endpoint.id ? (
                      <tr className="border-b border-border/60 bg-surface-muted/30">
                        <td colSpan={8} className="px-5 py-3">
                          <div className="grid gap-3 lg:grid-cols-3">
                            <div>
                              <p className="text-2xs uppercase tracking-wider text-muted-foreground">Evidence</p>
                              <ul className="mt-1 space-y-0.5">
                                {endpoint.evidence.map((item, index) => (
                                  <li key={index} className="text-2xs text-muted-foreground">
                                    {item}
                                  </li>
                                ))}
                              </ul>
                            </div>
                            <div>
                              <p className="text-2xs uppercase tracking-wider text-muted-foreground">Models</p>
                              <p className="mt-1 text-2xs text-muted-foreground">
                                request: <span className="mono">{endpoint.request_model ?? "—"}</span>
                                <br />
                                response: <span className="mono">{endpoint.response_model ?? "—"}</span>
                              </p>
                            </div>
                            <div>
                              <p className="text-2xs uppercase tracking-wider text-muted-foreground">
                                Declarations {(endpoint.declarations?.length ?? 1) > 1 ? `(${endpoint.declarations?.length})` : ""}
                              </p>
                              <ul className="mt-1 space-y-1">
                                {(endpoint.declarations ?? []).map((declaration) => (
                                  <li key={`${declaration.path}:${declaration.line ?? 0}`} className="flex items-center gap-1.5">
                                    <PathLink path={declaration.path} line={declaration.line} compact />
                                    {declaration.is_example ? <span className="text-2xs text-amber-200/80">example</span> : null}
                                    {declaration.is_test ? <span className="text-2xs text-sky-200/80">test</span> : null}
                                  </li>
                                ))}
                              </ul>
                            </div>
                            <div>
                              <p className="text-2xs uppercase tracking-wider text-muted-foreground">Notes</p>
                              <p className="mt-1 text-2xs text-muted-foreground">
                                {endpoint.notes ??
                                  `Auth marker ${endpoint.auth_required ? "present" : "absent"} on this handler. Frameworks: ${endpoint.framework ?? "unknown"}.`}
                              </p>
                            </div>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </React.Fragment>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {(payload.stats.from_examples ?? 0) + (payload.stats.from_tests ?? 0) > 0 ? (
        <InlineNote className="flex items-start gap-2">
          <Route className="mt-0.5 size-3.5 shrink-0" />
          <span>
            {(payload.stats.from_examples ?? 0) + (payload.stats.from_tests ?? 0)} of {payload.stats.total} endpoints are
            declared in example or test applications rather than shipped code
            {payload.stats.from_examples ? ` (${payload.stats.from_examples} example` : " (0 example"}
            {payload.stats.from_tests ? `, ${payload.stats.from_tests} test)` : ", 0 test)"}. That is expected for a library:
            the repository has no server of its own. Use the source filter to see only application routes.
          </span>
        </InlineNote>
      ) : null}

      <InlineNote className="flex items-start gap-2">
        <ShieldQuestion className="mt-0.5 size-3.5 shrink-0" />
        <span>
          Auth detection is static: RepoLens looks for auth dependencies (e.g. <span className="mono">Depends(get_current_user)</span>),
          guards, middleware and <span className="mono">@login_required</span>-style decorators. A route marked “none found” may still be
          protected globally — check the app-level middleware in the Architecture view. “inline” means the tracer found no
          resolvable call from the handler into a service or repository module ({formatNumber(payload.stats.total)} endpoints
          analysed).
        </span>
      </InlineNote>
    </div>
  );
}

export default function ApisPage() {
  return (
    <RunGate title="Analyse a repository to list its API surface">
      <ApiBody />
    </RunGate>
  );
}
