"use client";

import * as React from "react";
import Link from "next/link";
import {
  BadgeCheck,
  ChevronDown,
  CircleSlash,
  GitBranch,
  Github,
  Loader2,
  Play,
  RefreshCw,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { StatusPill } from "@/components/ui/states";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/menus";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { resolveRepo, type ResolveResponse } from "@/lib/api";
import { formatRelative, truncate } from "@/lib/utils";

const EXAMPLES = [
  "https://github.com/fastapi/full-stack-fastapi-template",
  "https://github.com/tiangolo/fastapi",
  "https://github.com/pallets/flask",
];

export function RepoBar() {
  const { analysis, repo, analyses, startAnalysis, starting, selectAnalysis, remove, cancel, refreshList } = useAnalysisContext();
  const [url, setUrl] = React.useState("");
  const [branch, setBranch] = React.useState<string | null>(null);
  const [branches, setBranches] = React.useState<ResolveResponse["branches"]>([]);
  const [branchLoading, setBranchLoading] = React.useState(false);
  const [branchError, setBranchError] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState(false);

  const loadBranches = React.useCallback(async (target: string) => {
    const value = target.trim();
    if (!value) {
      setBranchError("Enter a repository URL first.");
      return;
    }
    setBranchLoading(true);
    setBranchError(null);
    try {
      const payload = await resolveRepo(value);
      setBranches(payload.branches);
      setUrl(payload.canonical_url);
      setBranch((current) => current || payload.repo.default_branch);
      if (!payload.branches.length) setBranchError("GitHub returned no branches for this repository.");
    } catch (cause) {
      setBranches([]);
      setBranchError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBranchLoading(false);
    }
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = url.trim();
    if (!value) return;
    await startAnalysis(value, branch);
    setBranch(null);
    setBranches([]);
  };

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur-md">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3 lg:px-6">
        <Link href="/" className="flex items-center gap-2 lg:hidden">
          <Sparkles className="size-4 text-primary" />
          <span className="text-sm font-semibold">RepoLens</span>
        </Link>

        <form onSubmit={submit} className="flex min-w-[280px] flex-1 items-center gap-2">
          <div className="relative flex-1">
            <Github className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://github.com/owner/repository"
              spellCheck={false}
              autoComplete="off"
              className="pl-8"
              aria-label="GitHub repository URL"
            />
          </div>

          <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
              <Button type="button" variant="outline" size="default" onClick={() => { setOpen(true); if (!branches.length) void loadBranches(url); }}>
                <GitBranch />
                <span className="mono max-w-32 truncate text-xs">{branch || "branch"}</span>
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-72">
              <p className="px-1 pb-2 text-2xs uppercase tracking-wider text-muted-foreground">Branch to analyse</p>
              {branchLoading ? (
                <p className="flex items-center gap-2 px-1 py-3 text-xs text-muted-foreground">
                  <Loader2 className="size-3.5 animate-spin" /> Reading branches from GitHub…
                </p>
              ) : branchError ? (
                <p className="px-1 py-2 text-xs text-rose-300">{branchError}</p>
              ) : branches.length ? (
                <div className="max-h-64 space-y-0.5 overflow-y-auto scrollbar-thin">
                  {branches.map((entry) => (
                    <button
                      key={entry.name}
                      type="button"
                      onClick={() => {
                        setBranch(entry.name);
                        setOpen(false);
                      }}
                      className={`flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-secondary/70 ${
                        branch === entry.name ? "text-primary" : "text-muted-foreground"
                      }`}
                    >
                      <span className="mono truncate">{entry.name}</span>
                      {entry.default ? <Badge variant="secondary">default</Badge> : null}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="px-1 py-2 text-xs text-muted-foreground">No branch information yet.</p>
              )}
            </PopoverContent>
          </Popover>

          <Button type="submit" loading={starting} disabled={!url.trim() || Boolean(analysis && (analysis.status === "queued" || analysis.status === "running"))}>
            {starting ? "Analysing" : "Analyze Repository"}
            {!starting ? <Play className="size-3.5" /> : null}
          </Button>
        </form>

        <div className="flex items-center gap-2">
          {analysis ? <StatusPill status={analysis.status} /> : <Badge variant="outline">no run selected</Badge>}

          {analysis && (analysis.status === "queued" || analysis.status === "running") ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="icon-sm" onClick={() => void cancel()}>
                  <X />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Cancel this analysis</TooltipContent>
            </Tooltip>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="icon-sm" onClick={() => void refreshList()}>
                  <RefreshCw />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Reload the run list</TooltipContent>
            </Tooltip>
          )}

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="default" className="max-w-64">
                <span className="truncate text-xs">{repo?.full_name ?? "Recent analyses"}</span>
                <ChevronDown className="size-3.5 opacity-60" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-80">
              <DropdownMenuLabel>Recent analyses</DropdownMenuLabel>
              {analyses.length === 0 ? (
                <p className="px-2 py-3 text-xs text-muted-foreground">Nothing analysed yet. Paste a URL above.</p>
              ) : (
                analyses.map((run) => (
                  <DropdownMenuItem
                    key={run.id}
                    className="flex-col items-start gap-1"
                    onSelect={() => selectAnalysis(run.id)}
                  >
                    <div className="flex w-full items-center justify-between gap-2">
                      <span className="truncate text-xs font-medium">
                        {(run.repo?.full_name ?? run.repo_id) || run.id}
                      </span>
                      <StatusPill status={run.status} />
                    </div>
                    <div className="flex w-full items-center justify-between gap-2 text-2xs text-muted-foreground">
                      <span className="mono truncate">{run.branch ?? "default"} · {run.file_count} files</span>
                      <span>{formatRelative(run.finished_at ?? run.started_at)}</span>
                    </div>
                    {run.error?.message ? (
                      <span className="line-clamp-2 text-2xs text-rose-300/80">{truncate(run.error.message, 120)}</span>
                    ) : null}
                  </DropdownMenuItem>
                ))
              )}
              <DropdownMenuSeparator />
              <div className="px-2 pb-1 pt-1.5 text-2xs text-muted-foreground">
                Each repository keeps its 8 most recent runs.
              </div>
              {analysis ? (
                <DropdownMenuItem
                  className="text-rose-300 focus:bg-rose-500/10"
                  onSelect={(event) => {
                    event.preventDefault();
                    void remove(analysis.id);
                  }}
                >
                  <Trash2 className="size-3.5" /> Delete selected run
                </DropdownMenuItem>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {!repo ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-border/60 px-4 py-1.5 text-2xs text-muted-foreground lg:px-6">
          <BadgeCheck className="size-3" /> Try one of these:
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="mono rounded border border-border px-1.5 py-0.5 transition-colors hover:border-primary/50 hover:text-foreground"
              onClick={() => setUrl(example)}
            >
              {example.replace("https://github.com/", "")}
            </button>
          ))}
        </div>
      ) : analysis && (analysis.status === "queued" || analysis.status === "running") ? (
        <div className="flex items-center gap-3 border-t border-border/60 px-4 py-1.5 text-2xs text-muted-foreground lg:px-6">
          <Loader2 className="size-3 animate-spin text-primary" />
          <span className="text-foreground/90">{analysis.message || analysis.stage}</span>
          <span className="mono">{analysis.progress}%</span>
          <div className="h-1 w-40 overflow-hidden rounded-full bg-secondary">
            <div className="h-full rounded-full bg-primary transition-all duration-700" style={{ width: `${analysis.progress}%` }} />
          </div>
        </div>
      ) : analysis?.status === "failed" ? (
        <div className="flex items-center gap-2 border-t border-rose-500/30 bg-rose-500/5 px-4 py-1.5 text-2xs text-rose-200 lg:px-6">
          <CircleSlash className="size-3" />
          {analysis.error?.message ?? "The run failed."}
          {analysis.error?.hint ? <span className="text-rose-200/70">· {analysis.error.hint}</span> : null}
        </div>
      ) : null}
    </header>
  );
}
