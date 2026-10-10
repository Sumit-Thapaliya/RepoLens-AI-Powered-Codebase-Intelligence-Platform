"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Info, Lightbulb, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PathLink } from "@/components/common/path-link";
import { cn } from "@/lib/utils";
import type { Insight } from "@/lib/types";

const NAV_TARGETS = new Set([
  "overview",
  "architecture",
  "workflows",
  "dependencies",
  "apis",
  "database",
  "quality",
  "explorer",
  "impact",
  "search",
]);

function targetHref(target: string): string {
  if (NAV_TARGETS.has(target)) return `/${target}`;
  if (target.startsWith("/")) return target;
  if (target.includes("/") || /\.\w{1,5}$/.test(target)) return `/explorer?path=${encodeURIComponent(target)}`;
  return `/${target}`;
}

const SEVERITY_STYLES: Record<string, { ring: string; dot: string; text: string }> = {
  critical: { ring: "border-rose-500/30", dot: "bg-rose-400", text: "text-rose-300" },
  warning: { ring: "border-amber-500/30", dot: "bg-amber-400", text: "text-amber-300" },
  positive: { ring: "border-emerald-500/30", dot: "bg-emerald-400", text: "text-emerald-300" },
  info: { ring: "border-border", dot: "bg-sky-400", text: "text-sky-300" },
};

/** "AI Insights" - these are deterministic findings from the analysis artefacts. */
export function InsightsPanel({ insights, loading }: { insights: Insight[]; loading: boolean }) {
  const router = useRouter();
  const [expanded, setExpanded] = React.useState<string | null>(insights[0]?.id ?? null);

  return (
    <section className="panel flex max-h-[42rem] flex-col overflow-hidden">
      <div className="panel-header">
        <span className="panel-title flex items-center gap-2">
          <Lightbulb className="size-3.5 text-primary" /> AI Insights
        </span>
        <span className="text-2xs text-muted-foreground">{insights.length} findings</span>
      </div>
      <div className="flex items-center gap-2 border-b border-border bg-surface-muted/30 px-4 py-2 text-2xs text-muted-foreground">
        <Info className="size-3 shrink-0" />
        Derived from the parsed graph, endpoints and database model — not from an LLM guess.
      </div>

      <div className="flex-1 overflow-y-auto p-3 scrollbar-thin">
        {loading ? (
          <p className="flex items-center justify-center gap-2 py-10 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" /> Computing insights…
          </p>
        ) : insights.length === 0 ? (
          <p className="px-2 py-10 text-center text-xs text-muted-foreground">No notable findings for this repository.</p>
        ) : (
          <ul className="space-y-2">
            {insights.map((insight) => {
              const style = SEVERITY_STYLES[insight.severity] ?? SEVERITY_STYLES.info;
              const open = expanded === insight.id;
              return (
                <li key={insight.id} className={cn("rounded-lg border bg-surface-muted/30 transition-colors", style.ring)}>
                  <button
                    type="button"
                    className="flex w-full items-start gap-2.5 p-3 text-left"
                    onClick={() => setExpanded(open ? null : insight.id)}
                  >
                    <span className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", style.dot)} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs font-medium leading-snug">{insight.title}</span>
                      <span className={cn("mt-0.5 block text-2xs", style.text)}>{insight.kind}</span>
                    </span>
                  </button>
                  {open ? (
                    <div className="space-y-2.5 px-3 pb-3">
                      <p className="text-2xs leading-relaxed text-muted-foreground">{insight.detail}</p>
                      {insight.evidence?.length ? (
                        <div className="flex flex-wrap gap-1.5">
                          {insight.evidence.slice(0, 5).map((item, index) =>
                            item.path ? (
                              <PathLink key={index} path={item.path} line={item.line} label={item.label ?? undefined} compact className="max-w-full" />
                            ) : (
                              <span key={index} className="text-2xs text-muted-foreground">
                                {item.label}
                              </span>
                            ),
                          )}
                        </div>
                      ) : null}
                      {insight.actions?.length ? (
                        <div className="flex flex-wrap gap-1.5 pt-0.5">
                          {insight.actions.map((action) => (
                            <Button
                              key={action.label}
                              size="xs"
                              variant="subtle"
                              onClick={() => router.push(targetHref(action.target))}
                            >
                              {action.label} <ArrowRight className="size-3" />
                            </Button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
