import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return new Intl.NumberFormat("en-US").format(value);
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function formatDuration(ms: number | null | undefined): string {
  if (!ms) return "-";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return "unknown";
  const date = new Date(value);
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (Number.isNaN(seconds)) return "unknown";
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 2_592_000) return `${Math.floor(seconds / 86_400)}d ago`;
  if (seconds < 31_536_000) return `${Math.floor(seconds / 2_592_000)}mo ago`;
  return `${Math.floor(seconds / 31_536_000)}y ago`;
}

export function basename(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
}

export function dirname(path: string): string {
  const parts = path.split("/");
  parts.pop();
  return parts.join("/") || "/";
}

export function languageLabel(language: string | null | undefined): string {
  if (!language) return "Text";
  const map: Record<string, string> = {
    python: "Python",
    typescript: "TypeScript",
    tsx: "TypeScript",
    javascript: "JavaScript",
    jsx: "JavaScript",
    go: "Go",
    java: "Java",
    ruby: "Ruby",
    php: "PHP",
    rust: "Rust",
    csharp: "C#",
    c: "C",
    cpp: "C++",
    json: "JSON",
    yaml: "YAML",
    markdown: "Markdown",
    shell: "Shell",
    docker: "Docker",
    html: "HTML",
    css: "CSS",
    sql: "SQL",
    unknown: "Text",
  };
  return map[language] ?? language.charAt(0).toUpperCase() + language.slice(1);
}

export function monacoLanguage(language: string | null | undefined): string {
  const map: Record<string, string> = {
    tsx: "typescript",
    jsx: "javascript",
    mts: "typescript",
    cts: "typescript",
    shell: "shell",
    docker: "dockerfile",
    csharp: "csharp",
    // monaco 0.52 ships JSON as a language service only; the JavaScript grammar
    // highlights JSON well enough for a read-only viewer.
    json: "javascript",
    jsonc: "javascript",
    batch: "bat",
    proto: "protobuf",
    vue: "html",
    svelte: "html",
    toml: "plaintext", // no TOML grammar in monaco 0.52
    make: "plaintext",
    text: "plaintext",
    unknown: "plaintext",
  };
  if (!language) return "plaintext";
  return map[language] ?? language;
}

export function layerColor(layer: string): string {
  const map: Record<string, string> = {
    ui: "#a78bfa",
    route: "#38bdf8",
    middleware: "#fbbf24",
    service: "#34d399",
    repository: "#c084fc",
    util: "#94a3b8",
    config: "#737373",
    test: "#4ade80",
    entrypoint: "#fb923c",
    other: "#64748b",
  };
  return map[layer] ?? "#64748b";
}

export function layerLabel(layer: string): string {
  const map: Record<string, string> = {
    ui: "UI",
    route: "API",
    middleware: "Middleware",
    service: "Service",
    repository: "Data",
    util: "Util",
    config: "Config",
    test: "Test",
    entrypoint: "Entry",
    other: "Other",
  };
  return map[layer] ?? layer;
}

export function severityColor(severity: string): string {
  const map: Record<string, string> = {
    high: "text-rose-400 border-rose-500/30 bg-rose-500/10",
    medium: "text-amber-300 border-amber-500/30 bg-amber-500/10",
    low: "text-sky-300 border-sky-500/30 bg-sky-500/10",
    info: "text-slate-300 border-slate-500/30 bg-slate-500/10",
    warning: "text-amber-300 border-amber-500/30 bg-amber-500/10",
    critical: "text-rose-400 border-rose-500/30 bg-rose-500/10",
    positive: "text-emerald-300 border-emerald-500/30 bg-emerald-500/10",
  };
  return map[severity] ?? map.info;
}

export function methodColor(method: string): string {
  const primary = method.split("/")[0];
  const map: Record<string, string> = {
    GET: "text-sky-300 border-sky-500/30 bg-sky-500/10",
    POST: "text-emerald-300 border-emerald-500/30 bg-emerald-500/10",
    PUT: "text-amber-300 border-amber-500/30 bg-amber-500/10",
    PATCH: "text-amber-300 border-amber-500/30 bg-amber-500/10",
    DELETE: "text-rose-300 border-rose-500/30 bg-rose-500/10",
    WS: "text-violet-300 border-violet-500/30 bg-violet-500/10",
    ANY: "text-slate-300 border-slate-500/30 bg-slate-500/10",
    USE: "text-slate-300 border-slate-500/30 bg-slate-500/10",
    ACTION: "text-violet-300 border-violet-500/30 bg-violet-500/10",
  };
  return map[primary] ?? map.ANY;
}

export function truncate(value: string, max = 120): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}
