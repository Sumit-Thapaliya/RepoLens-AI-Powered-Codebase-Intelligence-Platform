"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, History, RotateCcw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/states";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { formatDuration, formatRelative } from "@/lib/utils";

/** Bottom section of the overview: every stored run, with actions that work. */
export function RecentAnalyses() {
  const { analyses, analysisId, selectAnalysis, remove, repo } = useAnalysisContext();
  const router = useRouter();

  return (
    <section className="panel">
      <div className="panel-header">
        <span className="panel-title flex items-center gap-2">
          <History className="size-3.5 text-muted-foreground" /> Recent analyses
        </span>
        <Button size="xs" variant="outline" asChild>
          <Link href="/docs">
            Reports & export <ArrowRight className="size-3" />
          </Link>
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-2xs uppercase tracking-wider text-muted-foreground">
              <th className="px-5 py-2 font-medium">Repository</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Branch</th>
              <th className="px-3 py-2 text-right font-medium">Files</th>
              <th className="px-3 py-2 text-right font-medium">Endpoints</th>
              <th className="px-3 py-2 text-right font-medium">Duration</th>
              <th className="px-3 py-2 font-medium">Finished</th>
              <th className="px-5 py-2" />
            </tr>
          </thead>
          <tbody>
            {analyses.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-5 py-8 text-center text-muted-foreground">
                  No analyses stored yet.
                </td>
              </tr>
            ) : (
              analyses.map((run) => (
                <tr
                  key={run.id}
                  className={`border-b border-border/60 transition-colors last:border-0 hover:bg-secondary/30 ${
                    run.id === analysisId ? "bg-primary/5" : ""
                  }`}
                >
                  <td className="px-5 py-2.5">
                    <button type="button" className="text-left" onClick={() => selectAnalysis(run.id)}>
                      <span className="font-medium">{run.repo?.full_name ?? repo?.full_name ?? run.repo_id}</span>
                      <span className="mono ml-2 text-2xs text-muted-foreground">{run.id.slice(0, 10)}</span>
                    </button>
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusPill status={run.status} />
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge variant="outline" className="mono font-normal">
                      {run.branch ?? "default"}
                    </Badge>
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{run.parsed_count}/{run.file_count}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {typeof run.provider_info?.endpoints === "number" ? (run.provider_info.endpoints as number) : "-"}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{formatDuration(run.duration_ms)}</td>
                  <td className="px-3 py-2.5 text-muted-foreground">{formatRelative(run.finished_at ?? run.started_at)}</td>
                  <td className="px-5 py-2.5">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        title="Open this run"
                        onClick={() => {
                          selectAnalysis(run.id);
                          router.push("/");
                        }}
                      >
                        <ArrowRight />
                      </Button>
                      <Button size="icon-sm" variant="ghost" title="Delete this run" onClick={() => void remove(run.id)}>
                        <Trash2 />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <p className="flex items-center gap-2 border-t border-border px-5 py-2.5 text-2xs text-muted-foreground">
        <RotateCcw className="size-3" />
        Re-analysing the same repository creates a new run; the previous 8 runs per repository are kept and can be
        switched at any time from the run menu in the header.
      </p>
    </section>
  );
}
