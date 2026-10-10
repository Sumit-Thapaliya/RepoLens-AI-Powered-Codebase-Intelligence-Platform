import * as React from "react";
import { cn, formatNumber } from "@/lib/utils";

export interface DonutSegment {
  label: string;
  value: number;
  color: string;
}

/**
 * Dependency-free SVG donut chart. Each slice has a native tooltip (<title>), and the
 * optional legend lists every slice with its count and share.
 */
export function DonutChart({
  segments,
  size = 128,
  thickness = 16,
  centerValue,
  centerLabel,
  showLegend = true,
  className,
  ariaLabel,
}: {
  segments: DonutSegment[];
  size?: number;
  thickness?: number;
  centerValue?: React.ReactNode;
  centerLabel?: string;
  showLegend?: boolean;
  className?: string;
  ariaLabel?: string;
}) {
  const visible = segments.filter((segment) => segment.value > 0);
  const total = visible.reduce((sum, segment) => sum + segment.value, 0);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const center = size / 2;

  let consumed = 0;
  const arcs = visible.map((segment) => {
    const length = total > 0 ? (circumference * segment.value) / total : 0;
    const arc = (
      <circle
        key={segment.label}
        cx={center}
        cy={center}
        r={radius}
        fill="none"
        stroke={segment.color}
        strokeWidth={thickness}
        strokeDasharray={`${length} ${circumference - length}`}
        strokeDashoffset={-consumed}
        transform={`rotate(-90 ${center} ${center})`}
      >
        <title>{`${segment.label}: ${formatNumber(segment.value)} (${Math.round((segment.value / total) * 100)}%)`}</title>
      </circle>
    );
    consumed += length;
    return arc;
  });

  return (
    <div className={cn("flex flex-wrap items-center gap-5", className)}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={ariaLabel ?? "Chart"} className="shrink-0">
        <circle cx={center} cy={center} r={radius} fill="none" stroke="#1e2530" strokeWidth={thickness} />
        {arcs}
        {centerValue !== undefined ? (
          <text x={center} y={centerLabel ? center - 2 : center + 6} textAnchor="middle" fontSize={size >= 120 ? 22 : 18} fontWeight={600} fill="#e6edf7">
            {centerValue}
          </text>
        ) : null}
        {centerLabel ? (
          <text x={center} y={center + 14} textAnchor="middle" fontSize={10} fill="#8b98ab">
            {centerLabel}
          </text>
        ) : null}
      </svg>

      {showLegend ? (
        <ul className="grid min-w-[10rem] flex-1 gap-1.5">
          {segments.map((segment) => (
            <li key={segment.label} className="flex items-center justify-between gap-3 text-xs">
              <span className="flex min-w-0 items-center gap-2">
                <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: segment.color }} />
                <span className="truncate">{segment.label}</span>
              </span>
              <span className="shrink-0 tabular-nums text-muted-foreground">
                {formatNumber(segment.value)}
                {total > 0 ? ` · ${Math.round((segment.value / total) * 100)}%` : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
