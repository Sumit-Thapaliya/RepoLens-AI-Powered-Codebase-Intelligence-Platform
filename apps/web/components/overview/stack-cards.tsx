"use client";

import * as React from "react";
import { Boxes, Database as DatabaseIcon, FileWarning, Package, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Overview } from "@/lib/types";
import { getLanguages } from "@/lib/api";
import { cn, formatNumber, truncate } from "@/lib/utils";

const LANGUAGE_COLORS: Record<string, string> = {
  tsx: "#3178c6",
  typescript: "#3178c6",
  javascript: "#f1e05a",
  jsx: "#f1e05a",
  python: "#3572A5",
  go: "#00ADD8",
  java: "#b07219",
  ruby: "#701516",
  php: "#4F5D95",
  rust: "#dea584",
  csharp: "#178600",
  cpp: "#f34b7d",
  c: "#555555",
  json: "#a0a0a0",
  yaml: "#cb171e",
  markdown: "#8b949e",
  shell: "#89e051",
  html: "#e34c26",
  css: "#563d7c",
  docker: "#384d54",
  sql: "#e38c00",
  restructuredtext: "#8b949e",
  text: "#8b949e",
  toml: "#9c4221",
  ini: "#6b7280",
  batch: "#c1f12e",
  xml: "#0060ac",
  make: "#427819",
  vue: "#41b883",
  svelte: "#ff3e00",
  unknown: "#6b7280",
};

export function LanguageCard({ overview }: { overview: Overview }) {
  const languages = overview.languages.slice(0, 10);
  const [deepLanguages, setDeepLanguages] = React.useState<Set<string> | null>(null);

  React.useEffect(() => {
    let active = true;
    void getLanguages()
      .then((payload) => {
        if (!active) return;
        const names = new Set<string>();
        (payload?.deep_analysis ?? []).forEach((entry: { language?: string }) => {
          if (entry?.language) names.add(entry.language);
        });
        setDeepLanguages(names);
      })
      .catch(() => setDeepLanguages(null));
    return () => {
      active = false;
    };
  }, []);

  const indexedOnly = languages.filter((entry) => deepLanguages && !deepLanguages.has(entry.language));

  return (
    <section className="panel">
      <div className="panel-header">
        <span className="panel-title">Languages</span>
        <span className="text-2xs text-muted-foreground">
          counted from {formatNumber(overview.files)} files
          {indexedOnly.length ? " · dimmed entries are indexed for search, not parsed" : ""}
        </span>
      </div>
      <div className="p-5 pt-4">
        <div className="flex h-2 overflow-hidden rounded-full border border-border/60">
          {languages.map((entry) => (
            <Tooltip key={entry.language}>
              <TooltipTrigger asChild>
                <div
                  style={{ width: `${Math.max(entry.percent, 0.6)}%`, backgroundColor: LANGUAGE_COLORS[entry.language] ?? "#6b7280" }}
                  className="h-full"
                />
              </TooltipTrigger>
              <TooltipContent>
                {entry.label}: {entry.files} files · {formatNumber(entry.loc)} LOC ({entry.percent}%)
              </TooltipContent>
            </Tooltip>
          ))}
        </div>
        <ul className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-2">
          {languages.map((entry) => (
            <li key={entry.language} className="flex items-center justify-between gap-3 text-xs">
              <span className="flex min-w-0 items-center gap-2">
                <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: LANGUAGE_COLORS[entry.language] ?? "#6b7280" }} />
                <span className={cn("truncate", deepLanguages && !deepLanguages.has(entry.language) && "text-muted-foreground")}>
                  {entry.label}
                </span>
              </span>
              <span className="shrink-0 tabular-nums text-muted-foreground">
                {entry.files} files · {entry.percent}%
              </span>
            </li>
          ))}
          {languages.length === 0 ? <li className="text-xs text-muted-foreground">No parsable source files found.</li> : null}
        </ul>
      </div>
    </section>
  );
}

export function FrameworksCard({ overview }: { overview: Overview }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <span className="panel-title flex items-center gap-2">
          <Boxes className="size-3.5 text-muted-foreground" /> Frameworks & tooling
        </span>
        <span className="text-2xs text-muted-foreground">confidence-weighted evidence</span>
      </div>
      <div className="flex flex-wrap gap-2 p-5 pt-4">
        {overview.frameworks.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No framework markers found. RepoLens looks for dependency manifests, config files and import/usage patterns.
          </p>
        ) : (
          overview.frameworks.map((framework) => (
            <Tooltip key={framework.name}>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-2 rounded-lg border border-border bg-surface-muted/50 px-2.5 py-1.5">
                  <span className="text-xs font-medium">{framework.name}</span>
                  <Badge variant={framework.confidence >= 0.9 ? "success" : framework.confidence >= 0.7 ? "info" : "warning"} className="mono">
                    {(framework.confidence * 100).toFixed(0)}%
                  </Badge>
                </div>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-sm">
                <p className="text-2xs font-medium">{framework.ecosystem ?? "detected"} · evidence</p>
                <ul className="mt-1 list-disc pl-4 text-2xs text-muted-foreground">
                  {framework.evidence.slice(0, 5).map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              </TooltipContent>
            </Tooltip>
          ))
        )}
      </div>
    </section>
  );
}

export function DatabaseStackCard({ overview }: { overview: Overview }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <span className="panel-title flex items-center gap-2">
          <DatabaseIcon className="size-3.5 text-muted-foreground" /> Data layer
        </span>
        <span className="text-2xs text-muted-foreground">
          {overview.database_stats.models ?? 0} models · {overview.database_stats.queries ?? 0} queries
        </span>
      </div>
      <div className="space-y-2.5 p-5 pt-4">
        {overview.databases.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No database technology detected in manifests, config or ORM usage.
          </p>
        ) : (
          overview.databases.map((technology) => (
            <div key={technology.name} className="rounded-lg border border-border bg-surface-muted/40 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium">{technology.name}</span>
                <Badge variant="secondary">{technology.kind}</Badge>
              </div>
              <p className="mt-1 text-2xs leading-relaxed text-muted-foreground">
                {technology.evidence.slice(0, 2).map((item) => truncate(item, 90)).join(" · ")}
              </p>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

export function DependencyCard({ overview }: { overview: Overview }) {
  const dependencies = overview.top_dependencies.slice(0, 12);
  const max = dependencies[0]?.imports ?? 1;
  return (
    <section className="panel">
      <div className="panel-header">
        <span className="panel-title flex items-center gap-2">
          <Package className="size-3.5 text-muted-foreground" /> Most used external packages
        </span>
        <span className="text-2xs text-muted-foreground">{overview.resolve_stats.external ?? 0} external imports</span>
      </div>
      <div className="space-y-2 p-5 pt-4">
        {dependencies.length === 0 ? (
          <p className="text-xs text-muted-foreground">No external imports were resolved.</p>
        ) : (
          dependencies.map((dependency) => (
            <div key={dependency.name} className="flex items-center gap-3">
              <span className="mono w-44 shrink-0 truncate text-2xs" title={dependency.name}>
                {dependency.name}
              </span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-secondary">
                <div className="h-full rounded-full bg-primary/70" style={{ width: `${(dependency.imports / max) * 100}%` }} />
              </div>
              <span className="w-8 shrink-0 text-right text-2xs tabular-nums text-muted-foreground">{dependency.imports}</span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

export function DiagnosticsCard({ overview }: { overview: Overview }) {
  const failures = overview.parse_failures ?? [];
  const manifests = overview.manifests ?? [];
  return (
    <section className="panel">
      <div className="panel-header">
        <span className="panel-title flex items-center gap-2">
          <FileWarning className="size-3.5 text-muted-foreground" /> Parse diagnostics
        </span>
        <span className="text-2xs text-muted-foreground">
          {failures.length} failure(s) · {manifests.length} manifest(s)
        </span>
      </div>
      <div className="space-y-3 p-5 pt-4">
        {failures.length === 0 ? (
          <p className="flex items-center gap-2 text-xs text-emerald-300/90">
            <Sparkles className="size-3.5" /> Every supported file parsed cleanly.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {failures.slice(0, 8).map((failure) => (
              <li key={failure.path} className="rounded-md border border-amber-500/20 bg-amber-500/5 px-2.5 py-2">
                <p className="mono truncate text-2xs text-amber-100">{failure.path}</p>
                <p className="mt-0.5 text-2xs text-muted-foreground">{failure.error}</p>
              </li>
            ))}
            {failures.length > 8 ? (
              <li className="text-2xs text-muted-foreground">+{failures.length - 8} more (see the analysis bundle)</li>
            ) : null}
          </ul>
        )}

        {manifests.length ? (
          <div>
            <p className="text-2xs uppercase tracking-wider text-muted-foreground">Manifests</p>
            <ul className="mt-1.5 grid gap-1.5 sm:grid-cols-2">
              {manifests.slice(0, 6).map((manifest) => (
                <li key={manifest.path} className="rounded-md border border-border/70 px-2.5 py-1.5">
                  <p className="mono truncate text-2xs" title={manifest.path}>
                    {manifest.path}
                  </p>
                  <p className="text-2xs text-muted-foreground">
                    {manifest.name ? `${manifest.name}${manifest.version ? ` ${manifest.version}` : ""} · ` : ""}
                    {manifest.dependencies} dependencies
                  </p>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {overview.ci_workflows?.length ? (
          <div>
            <p className="text-2xs uppercase tracking-wider text-muted-foreground">CI workflows</p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {overview.ci_workflows.map((workflow) => (
                <Badge key={workflow} variant="outline" className="mono font-normal">
                  {workflow}
                </Badge>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-2xs text-muted-foreground">No GitHub Actions workflows detected in .github/workflows.</p>
        )}
      </div>
    </section>
  );
}
