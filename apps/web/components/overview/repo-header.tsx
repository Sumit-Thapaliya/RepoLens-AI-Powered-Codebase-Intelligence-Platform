"use client";

import * as React from "react";
import Link from "next/link";
import { Archive, ExternalLink, FileText, GitFork, GitBranch, Scale, Star, Timer, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Analysis, RepoMetadata } from "@/lib/types";
import { formatDuration, formatNumber, formatRelative } from "@/lib/utils";

export function RepoHeader({ repo, run }: { repo: RepoMetadata; run: Analysis }) {
  const facts = [
    { icon: Star, label: `${formatNumber(repo.stars)} stars` },
    { icon: GitFork, label: `${formatNumber(repo.forks)} forks` },
    { icon: Scale, label: repo.license || "no license" },
    { icon: GitBranch, label: `${run.branch || repo.default_branch}${run.commit_sha ? ` @ ${run.commit_sha.slice(0, 7)}` : ""}` },
    { icon: Timer, label: `${formatDuration(run.duration_ms)} · ${formatRelative(run.finished_at ?? run.started_at)}` },
  ];

  return (
    <div className="panel overflow-hidden">
      <div className="relative">
        <div className="grid-lines absolute inset-0 opacity-40" />
        <div className="relative flex flex-wrap items-start justify-between gap-4 p-5">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-semibold tracking-tight">{repo.full_name}</h1>
              {repo.archived ? (
                <Badge variant="warning">
                  <Archive /> archived
                </Badge>
              ) : null}
              {repo.is_fork ? <Badge variant="outline">fork</Badge> : null}
              {repo.primary_language ? <Badge variant="secondary">{repo.primary_language}</Badge> : null}
            </div>
            <p className="mt-1.5 max-w-3xl text-xs leading-relaxed text-muted-foreground">
              {repo.description || "This repository has no description on GitHub."}
            </p>
            <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-2xs text-muted-foreground">
              {facts.map((fact) => (
                <span key={fact.label} className="flex items-center gap-1.5">
                  <fact.icon className="size-3" />
                  {fact.label}
                </span>
              ))}
            </div>
            {repo.topics?.length ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {repo.topics.slice(0, 8).map((topic) => (
                  <Badge key={topic} variant="outline" className="font-normal">
                    {topic}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" asChild>
              <a href={repo.html_url} target="_blank" rel="noreferrer noopener">
                <ExternalLink /> GitHub
              </a>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link href="/docs">
                <FileText /> Reports
              </Link>
            </Button>
          </div>
        </div>
      </div>

      {run.warnings.length || run.failed_count ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border bg-surface-muted/40 px-5 py-2 text-2xs text-muted-foreground">
          <span className="flex items-center gap-1.5 text-amber-200/90">
            <TriangleAlert className="size-3" />
            {run.failed_count} file(s) could not be parsed
          </span>
          {run.skipped_count ? <span>{run.skipped_count} file(s) skipped (binary / too large / ignored)</span> : null}
          <span>
            {run.parsed_count} of {run.file_count} files parsed
          </span>
          {run.warnings.slice(0, 2).map((warning, index) => (
            <span key={index} className="truncate" title={warning.message}>
              {warning.message}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
