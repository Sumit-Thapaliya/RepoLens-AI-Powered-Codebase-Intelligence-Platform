"use client";

import * as React from "react";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Check, Copy, Loader2, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Search, ShieldAlert } from "lucide-react";
import dynamic from "next/dynamic";
import { RunGate } from "@/components/app/run-gate";

// Monaco touches `window` / web workers, so the viewer is loaded client-side only.
const CodeViewer = dynamic(() => import("@/components/explorer/code-viewer").then((mod) => mod.CodeViewer), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> Loading editor…
    </div>
  ),
});
import { FileTree } from "@/components/explorer/file-tree";
import { FileInsights } from "@/components/explorer/file-insights";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/menus";
import { EmptyState, ErrorState, SkeletonCard, useToast } from "@/components/ui/states";
import { ApiError, getFile, getFileTree, getSymbolReferences, getSymbols } from "@/lib/api";
import type { FileNode, FilePayload, SymbolInfo } from "@/lib/types";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { cn } from "@/lib/utils";

function SymbolJump({
  analysisId,
  onPick,
}: {
  analysisId: string;
  onPick: (symbol: SymbolInfo) => void;
}) {
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState<SymbolInfo[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const payload = await getSymbols(analysisId, query.trim(), 20);
        if (!cancelled) {
          setResults(payload.symbols);
          setOpen(true);
        }
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 220);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [analysisId, query]);

  return (
    <Popover open={open && results.length > 0} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Jump to symbol…"
            className="h-8 w-56 pl-8 text-xs"
          />
        </div>
      </PopoverTrigger>
      <PopoverContent className="w-96 p-1">
        <p className="px-2 py-1.5 text-2xs uppercase tracking-wider text-muted-foreground">
          {loading ? "searching…" : `${results.length} symbol(s)`}
        </p>
        <div className="max-h-72 overflow-y-auto scrollbar-thin">
          {results.map((symbol) => (
            <button
              key={symbol.id}
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-secondary/70"
              onClick={() => {
                onPick(symbol);
                setOpen(false);
              }}
            >
              <Badge variant="outline" className="shrink-0 font-normal">
                {symbol.kind}
              </Badge>
              <span className="mono truncate text-xs">{symbol.name}</span>
              <span className="ml-auto shrink-0 truncate text-2xs text-muted-foreground" title={symbol.path}>
                {symbol.path}:{symbol.start_line}
              </span>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function ReferencesPopover({ analysisId, symbol }: { analysisId: string; symbol: string }) {
  const [references, setReferences] = React.useState<{ path: string; symbol: string; line: number; kind: string; via: string }[]>([]);
  const [loading, setLoading] = React.useState(false);
  const router = useRouter();

  return (
    <Popover
      onOpenChange={async (open) => {
        if (!open || references.length) return;
        setLoading(true);
        try {
          const payload = await getSymbolReferences(analysisId, symbol, 40);
          setReferences(payload.references);
        } finally {
          setLoading(false);
        }
      }}
    >
      <PopoverTrigger asChild>
        <Button size="xs" variant="outline">
          References
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-96 p-1">
        <p className="px-2 py-1.5 text-2xs uppercase tracking-wider text-muted-foreground">
          {loading ? "resolving…" : `${references.length} reference(s) to ${symbol}`}
        </p>
        <div className="max-h-72 overflow-y-auto scrollbar-thin">
          {references.map((reference, index) => (
            <button
              key={index}
              type="button"
              className="block w-full rounded-md px-2 py-1.5 text-left transition-colors hover:bg-secondary/70"
              onClick={() => router.push(`/explorer?path=${encodeURIComponent(reference.path)}&line=${reference.line}`)}
            >
              <span className="mono block truncate text-2xs">{reference.path}:{reference.line}</span>
              <span className="text-2xs text-muted-foreground">
                {reference.symbol} · via {reference.via}
              </span>
            </button>
          ))}
          {!loading && references.length === 0 ? (
            <p className="px-2 py-3 text-2xs text-muted-foreground">No references found in parsed files.</p>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** Choose something interesting to open first: a parsed, non-dotfile source file. */
function pickDefaultFile(root: FileNode): string | null {
  const candidates: { path: string; depth: number; score: number }[] = [];
  const walk = (node: FileNode, depth: number) => {
    if (node.type === "file") {
      const name = node.name.toLowerCase();
      let score = 0;
      if (node.parsed) score += 2;
      if (!name.startsWith(".")) score += 1;
      if (name.startsWith("readme")) score += 2;
      if (/(^|\/)(main|app|index|__init__)\.\w+$/.test(node.path)) score += 1;
      if (["markdown", "unknown", "json", "yaml", "shell", "docker"].includes(node.language ?? "")) score -= 2;
      candidates.push({ path: node.path, depth, score });
    }
    (node.children ?? []).forEach((child) => walk(child, depth + 1));
  };
  root.children?.forEach((child) => walk(child, 0));
  candidates.sort((a, b) => b.score - a.score || a.depth - b.depth || a.path.length - b.path.length);
  return candidates[0]?.path ?? null;
}

function ExplorerBody() {
  const { analysisId } = useAnalysisContext();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { push } = useToast();

  const pathParam = searchParams.get("path");
  const lineParam = Number(searchParams.get("line") ?? 0) || null;

  const [root, setRoot] = React.useState<FileNode | null>(null);
  const [total, setTotal] = React.useState(0);
  const [treeError, setTreeError] = React.useState<ApiError | null>(null);
  const [file, setFile] = React.useState<FilePayload | null>(null);
  const [fileError, setFileError] = React.useState<ApiError | null>(null);
  const [loadingFile, setLoadingFile] = React.useState(false);
  const [selectedPath, setSelectedPath] = React.useState<string | null>(pathParam);
  const [focusSymbol, setFocusSymbol] = React.useState<{ start: number; end: number; name: string } | null>(null);
  const [showTree, setShowTree] = React.useState(true);
  const [showPanel, setShowPanel] = React.useState(true);
  const [copied, setCopied] = React.useState(false);

  const openFile = React.useCallback(
    async (path: string, line?: number | null) => {
      if (!analysisId) return;
      setSelectedPath(path);
      setLoadingFile(true);
      setFileError(null);
      setFocusSymbol(null);
      try {
        const payload = await getFile(analysisId, path);
        setFile(payload);
        if (line) router.replace(`/explorer?path=${encodeURIComponent(path)}&line=${line}`);
        else router.replace(`/explorer?path=${encodeURIComponent(path)}`);
      } catch (cause) {
        setFile(null);
        setFileError(cause instanceof ApiError ? cause : new ApiError(String(cause)));
      } finally {
        setLoadingFile(false);
      }
    },
    [analysisId, router],
  );

  /* Load the file tree once per analysis and open the first file (or the one in the URL). */
  const bootstrapped = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!analysisId || bootstrapped.current === analysisId) return;
    bootstrapped.current = analysisId;
    let cancelled = false;
    (async () => {
      try {
        const payload = await getFileTree(analysisId);
        if (cancelled) return;
        setRoot(payload.root);
        setTotal(payload.total);
        const target = pathParam || pickDefaultFile(payload.root);
        if (target) void openFile(target, lineParam);
      } catch (cause) {
        if (!cancelled) setTreeError(cause instanceof ApiError ? cause : new ApiError(String(cause)));
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId, pathParam, lineParam, openFile]);

  /* Follow in-app navigation (e.g. from the dependency graph or the impact view). */
  React.useEffect(() => {
    if (pathParam && pathParam !== selectedPath) void openFile(pathParam, lineParam);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathParam, lineParam]);

  if (treeError && !root) return <ErrorState error={treeError} className="m-6" title="Could not load the file tree" />;
  if (!root) return <SkeletonCard className="m-6" lines={12} />;

  return (
    <div className="flex h-[calc(100svh-9rem)] min-h-0">
      {showTree ? (
        <div className="flex w-64 shrink-0 flex-col border-r border-border bg-surface/40">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-2xs uppercase tracking-wider text-muted-foreground">{total} files</span>
            <Button size="icon-sm" variant="ghost" title="Hide tree" onClick={() => setShowTree(false)}>
              <PanelLeftClose />
            </Button>
          </div>
          <FileTree tree={root.children ?? []} selected={selectedPath} onSelect={(path) => void openFile(path)} />
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
          <Button size="icon-sm" variant="ghost" title={showTree ? "Hide tree" : "Show tree"} onClick={() => setShowTree((value) => !value)}>
            {showTree ? <PanelLeftClose /> : <PanelLeftOpen />}
          </Button>
          {analysisId ? <SymbolJump analysisId={analysisId} onPick={(symbol) => {
            setFocusSymbol({ start: symbol.start_line, end: symbol.end_line, name: symbol.name });
            void openFile(symbol.path, symbol.start_line);
          }} /> : null}
          {file ? (
            <>
              <Button
                size="xs"
                variant="outline"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(file.path);
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1500);
                  } catch {
                    push({ tone: "error", title: "Clipboard blocked" });
                  }
                }}
              >
                {copied ? <Check className="text-emerald-400" /> : <Copy />} path
              </Button>
              <Button size="xs" variant="outline" onClick={() => router.push(`/impact?path=${encodeURIComponent(file.path)}`)}>
                <ShieldAlert /> Impact
              </Button>
              {focusSymbol ? (
                <>
                  <Badge variant="secondary" className="mono">
                    {focusSymbol.name} L{focusSymbol.start}–{focusSymbol.end}
                  </Badge>
                  {analysisId ? <ReferencesPopover analysisId={analysisId} symbol={focusSymbol.name} /> : null}
                </>
              ) : null}
            </>
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            {loadingFile ? <span className="text-2xs text-muted-foreground">loading…</span> : null}
            <Button size="icon-sm" variant="ghost" title={showPanel ? "Hide intelligence panel" : "Show intelligence panel"} onClick={() => setShowPanel((value) => !value)}>
              {showPanel ? <PanelRightClose /> : <PanelRightOpen />}
            </Button>
          </div>
        </div>

        <div className="min-h-0 flex-1">
          {fileError ? (
            <ErrorState
              error={fileError}
              title={`Could not open ${selectedPath ?? "file"}`}
              onRetry={() => selectedPath && void openFile(selectedPath, lineParam)}
              className="m-4"
            />
          ) : file && analysisId ? (
            <CodeViewer file={file} targetLine={lineParam} focusSymbol={focusSymbol} />
          ) : (
            <EmptyState title="Select a file" detail="Pick a file from the tree or search for a symbol to jump straight to it." />
          )}
        </div>
      </div>

      {showPanel && file && analysisId ? (
        <div className="hidden w-80 shrink-0 border-l border-border bg-surface/30 p-3 xl:block">
          <FileInsights
            file={file}
            onJump={(symbol) => {
              setFocusSymbol({ start: symbol.start_line, end: symbol.end_line, name: symbol.name });
              void openFile(symbol.path, symbol.start_line);
            }}
            onOpenFile={(path, line) => void openFile(path, line)}
            onImpact={(path, symbol) => router.push(`/impact?path=${encodeURIComponent(path)}${symbol ? `&symbol=${encodeURIComponent(symbol)}` : ""}`)}
          />
        </div>
      ) : null}
    </div>
  );
}

export default function ExplorerPage() {
  return (
    <RunGate title="Analyse a repository to explore its code">
      <Suspense fallback={<SkeletonCard className="m-6" lines={10} />}>
        <ExplorerBody />
      </Suspense>
    </RunGate>
  );
}
