import * as React from "react";
import { cn, formatNumber } from "@/lib/utils";

export interface BarItem {
  label: string;
  value: number;
  color?: string;
  hint?: string;
}

/** Horizontal bars scaled to the largest value. Pure CSS, no chart library. */
export function BarList({
  items,
  formatValue = formatNumber,
  emptyText = "Nothing to show.",
  className,
}: {
  items: BarItem[];
  formatValue?: (value: number) => string;
  emptyText?: string;
  className?: string;
}) {
  if (items.length === 0) return <p className="text-xs text-muted-foreground">{emptyText}</p>;
  const largest = Math.max(1, ...items.map((item) => item.value));
  return (
    <ul className={cn("space-y-3", className)}>
      {items.map((item) => (
        <li key={item.label}>
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <span className="min-w-0 truncate" title={item.hint ?? item.label}>
              {item.label}
            </span>
            <span className="shrink-0 tabular-nums text-muted-foreground">{formatValue(item.value)}</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-muted">
            <div
              className={cn("h-full rounded-full transition-[width] duration-500", !item.color && "bg-primary")}
              style={{ width: `${Math.max(2, (item.value / largest) * 100)}%`, backgroundColor: item.color }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
