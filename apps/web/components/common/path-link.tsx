"use client";

import * as React from "react";
import Link from "next/link";
import { FileCode2, Layers } from "lucide-react";
import { cn, basename, dirname, layerColor, layerLabel } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/** Clickable file reference that opens the Code Explorer at the exact line. */
export function PathLink({
  path,
  line,
  className,
  label,
  showLine = true,
  compact = false,
}: {
  path: string;
  line?: number | null;
  className?: string;
  label?: string;
  showLine?: boolean;
  compact?: boolean;
}) {
  const href = `/explorer?path=${encodeURIComponent(path)}${line ? `&line=${line}` : ""}`;
  const text = label ?? (compact ? basename(path) : path);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link href={href} className={cn("path-chip max-w-full", className)}>
          <FileCode2 className="size-3 shrink-0" />
          <span className="truncate">{text}</span>
          {showLine && line ? <span className="text-muted-foreground/70">:{line}</span> : null}
        </Link>
      </TooltipTrigger>
      <TooltipContent side="top">
        <span className="mono">{path}</span>
        {line ? <span className="mono">:{line}</span> : null}
        {!compact && dirname(path) ? <div className="mt-1 text-2xs text-muted-foreground">{dirname(path)}</div> : null}
      </TooltipContent>
    </Tooltip>
  );
}

export function LayerBadge({ layer, className }: { layer: string; className?: string }) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs font-medium", className)}
      style={{
        color: layerColor(layer),
        borderColor: `${layerColor(layer)}55`,
        backgroundColor: `${layerColor(layer)}14`,
      }}
    >
      <Layers className="size-2.5" />
      {layerLabel(layer)}
    </span>
  );
}

export function KindBadge({ kind, className }: { kind: string; className?: string }) {
  const tone: Record<string, string> = {
    function: "border-sky-500/30 bg-sky-500/10 text-sky-300",
    method: "border-sky-500/30 bg-sky-500/10 text-sky-300",
    class: "border-violet-500/30 bg-violet-500/10 text-violet-300",
    interface: "border-violet-500/30 bg-violet-500/10 text-violet-300",
    type: "border-violet-500/30 bg-violet-500/10 text-violet-300",
    router: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    constant: "border-slate-500/30 bg-slate-500/10 text-slate-300",
    variable: "border-slate-500/30 bg-slate-500/10 text-slate-300",
  };
  return (
    <span className={cn("inline-flex rounded border px-1.5 py-0.5 text-2xs font-medium", tone[kind] ?? "border-border bg-secondary text-muted-foreground", className)}>
      {kind}
    </span>
  );
}
