"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { cn, formatNumber } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  href,
  tone = "default",
  className,
}: {
  label: string;
  value: number | string | null | undefined;
  hint?: string;
  icon?: React.ComponentType<{ className?: string }>;
  href?: string;
  tone?: "default" | "primary" | "accent" | "warning";
  className?: string;
}) {
  const display = typeof value === "number" ? formatNumber(value) : (value ?? "-");
  const body = (
    <div
      className={cn(
        "group relative overflow-hidden rounded-xl border border-border bg-surface/70 p-4 transition-colors hover:border-primary/40",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="kpi-label">{label}</p>
        {Icon ? (
          <Icon
            className={cn(
              "size-4",
              tone === "primary" ? "text-primary" : tone === "accent" ? "text-accent" : tone === "warning" ? "text-amber-300" : "text-muted-foreground",
            )}
          />
        ) : null}
      </div>
      <p className={cn("kpi-value mt-2", tone === "primary" && "text-primary", tone === "accent" && "text-accent")}>{display}</p>
      {hint ? <p className="mt-1 text-2xs leading-relaxed text-muted-foreground">{hint}</p> : null}
      {href ? (
        <ArrowUpRight className="absolute right-3 bottom-3 size-3.5 text-muted-foreground/0 transition-colors group-hover:text-primary" />
      ) : null}
    </div>
  );

  const wrapped = href ? (
    <Link href={href} className="block focus-visible:outline-none">
      {body}
    </Link>
  ) : (
    body
  );

  if (!hint) return wrapped;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{wrapped}</TooltipTrigger>
      <TooltipContent side="bottom">{hint}</TooltipContent>
    </Tooltip>
  );
}

export function MiniStat({ label, value, className }: { label: string; value: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-lg border border-border/70 bg-surface-muted/40 px-3 py-2", className)}>
      <p className="text-2xs uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm font-semibold tabular-nums">{value}</p>
    </div>
  );
}
