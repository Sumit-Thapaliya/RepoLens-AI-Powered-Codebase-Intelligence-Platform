"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Check, Copy, FileSearch, Filter, Search as SearchIcon, Type } from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { Badge } from "@/components/ui/badge";
import { Highlight } from "@/components/common/highlight";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, ErrorState, InlineNote, SkeletonCard, useToast } from "@/components/ui/states";
import { ApiError, grep, search as rankedSearch } from "@/lib/api";
import type { SearchHit } from "@/lib/types";
import { useAnalysisContext } from "@/components/providers/analysis-provider";

const EXAMPLE_QUERIES = [
  "password hash",
  "authenticate user",
  "session token",
  "load config settings",
  "send email",
];

interface GrepMatch {
  path: string;
  line: number;
  text: string;
  kind?: string;
}

type SearchMode = "ranked" | "text";

function SearchBody() {
  const { analysisId } = useAnalysisContext();
  const router = useRouter();
  const [mode, setMode] = React.useState<SearchMode>("ranked");
  const [query, setQuery] = React.useState("");
  const [hits, setHits] = React.useState<SearchHit[]>([]);
  const [matches, setMatches] = React.useState<GrepMatch[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<ApiError | null>(null);
  const [searched, setSearched] = React.useState(false);
  const [lastQuery, setLastQuery] = React.useState("");
  const [copiedPath, setCopiedPath] = React.useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const { push } = useToast();

  // "/" focuses the search box from anywhere on the page, unless the user is already typing.
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
      event.preventDefault();
      inputRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const copyPath = async (path: string) => {
    try {
      await navigator.clipboard.writeText(path);
      setCopiedPath(path);
      window.setTimeout(() => setCopiedPath((current) => (current === path ? null : current)), 1500);
    } catch {
      push({ tone: "error", title: "Could not copy the path", detail: "Your browser blocked clipboard access." });
    }
  };

  const runSearch = React.useCallback(
    async (text: string, nextMode: SearchMode = mode) => {
      const trimmed = text.trim();
      if (!analysisId || !trimmed) return;
      setLastQuery(trimmed);
      setLoading(true);
      setError(null);
      setSearched(true);
      try {
        if (nextMode === "ranked") {
          const payload = await rankedSearch(analysisId, trimmed, 20);
          setHits(payload.hits);
        } else {
          const payload = await grep(analysisId, trimmed, 120);
          setMatches(payload.matches);
        }
      } catch (cause) {
        setError(cause instanceof ApiError ? cause : new ApiError(String(cause)));
      } finally {
        setLoading(false);
      }
    },
    [analysisId, mode],
  );

  const open = (path: string, line?: number | null) =>
    router.push(`/explorer?path=${encodeURIComponent(path)}${line ? `&line=${line}` : ""}`);

  const switchMode = (value: string) => {
    const next = value === "text" ? "text" : "ranked";
    setMode(next);
    if (query.trim()) void runSearch(query, next);
  };

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-base font-semibold tracking-tight">Search</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Find files and symbols by path, name or identifier. Source files are not retained in the search index;
            open a result to fetch its source from GitHub at the analysed commit.
          </p>
        </div>
        <Badge variant="outline" className="font-normal">
          ranking: keyword match (no AI)
        </Badge>
      </div>

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void runSearch(query);
        }}
      >
        <div className="relative min-w-[300px] flex-1">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={mode === "ranked" ? "Identifiers, e.g. password_hash" : "Identifier words, e.g. get_user_by_email"}
            className="h-10 pl-9 pr-9"
          />
          <kbd className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rounded border border-border px-1.5 text-2xs text-muted-foreground">
            /
          </kbd>
        </div>
        <Tabs value={mode} onValueChange={switchMode}>
          <TabsList className="h-10">
            <TabsTrigger value="ranked" className="h-8">
              <SearchIcon className="size-3" /> Ranked
            </TabsTrigger>
            <TabsTrigger value="text" className="h-8">
              <Type className="size-3" /> Identifiers
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <Button type="submit" loading={loading} className="h-10">
          Search
        </Button>
      </form>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="flex items-center gap-1 text-2xs text-muted-foreground">
          <Filter className="size-3" /> try:
        </span>
        {EXAMPLE_QUERIES.map((example) => (
          <button
            key={example}
            type="button"
            className="rounded-full border border-border px-2.5 py-1 text-2xs text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
            onClick={() => {
              setQuery(example);
              void runSearch(example, mode);
            }}
          >
            {example}
          </button>
        ))}
      </div>

      {error ? <ErrorState error={error} onRetry={() => void runSearch(query)} /> : null}

      {lastQuery && !loading ? (
        <p className="text-xs text-muted-foreground">
          {mode === "ranked" ? hits.length : matches.length} {mode === "ranked" ? "ranked" : "exact"} result
          {(mode === "ranked" ? hits.length : matches.length) === 1 ? "" : "s"} for “{lastQuery}”
        </p>
      ) : null}

      <Tabs value={mode} onValueChange={switchMode}>
        <TabsContent value="ranked" className="mt-0">
          {loading && !hits.length ? (
            <SkeletonCard lines={8} />
          ) : hits.length ? (
            <ul className="space-y-2">
              {hits.map((hit) => (
                <li key={hit.id} className="panel p-4 transition-colors hover:border-primary/40">
                  <button type="button" className="w-full text-left" onClick={() => open(hit.path, hit.start_line)}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="mono truncate text-xs">
                        {hit.path}:{hit.start_line}
                      </span>
                      <span className="flex shrink-0 items-center gap-2">
                        <Badge variant="outline" className="font-normal">
                          {hit.kind}
                        </Badge>
                        {hit.symbol ? (
                          <Badge variant="secondary" className="mono">
                            {hit.symbol}
                          </Badge>
                        ) : null}
                        <span className="text-2xs tabular-nums text-muted-foreground">score {hit.score.toFixed(2)}</span>
                      </span>
                    </div>
                    <pre className="mono mt-2 max-h-40 overflow-hidden whitespace-pre-wrap break-words rounded-lg border border-border bg-surface-muted/50 p-3 text-[0.72rem] leading-relaxed text-muted-foreground">
                      <Highlight text={hit.snippet} query={lastQuery} />
                    </pre>
                  </button>
                  <div className="mt-2 flex justify-end">
                    <Button
                      variant="ghost"
                      size="xs"
                      onClick={() => void copyPath(hit.path)}
                      aria-label={`Copy path ${hit.path}`}
                    >
                      {copiedPath === hit.path ? <Check /> : <Copy />}
                      {copiedPath === hit.path ? "Copied" : "Copy path"}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          ) : searched ? (
            <EmptyState
              icon={FileSearch}
              title="No match"
              detail="Try fewer or different identifiers, or switch to the identifier search for exact symbol words."
            />
          ) : (
            <EmptyState
              icon={SearchIcon}
              title="Ranked search"
              detail="Type identifiers or file-path terms. Results point to matching files and symbols without storing source excerpts."
            />
          )}
        </TabsContent>

        <TabsContent value="text" className="mt-0">
          {loading && !matches.length ? (
            <SkeletonCard lines={8} />
          ) : matches.length ? (
            <ul className="panel divide-y divide-border overflow-hidden">
              {matches.map((match, index) => (
                <li key={`${match.path}-${match.line}-${index}`}>
                  <button
                    type="button"
                    className="w-full px-4 py-2 text-left transition-colors hover:bg-secondary/40"
                    onClick={() => open(match.path, match.line)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="mono truncate text-2xs">
                        {match.path}:{match.line}
                      </span>
                      {match.kind ? <Badge variant="outline">{match.kind}</Badge> : null}
                    </div>
                    <p className="mono mt-1 line-clamp-2 text-2xs text-muted-foreground">
                      <Highlight text={match.text} query={lastQuery} />
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          ) : searched ? (
            <EmptyState
              icon={Type}
              title={`No occurrence of “${query}”`}
              detail="This privacy-safe index matches all identifier terms in a file or symbol; it is not a byte-for-byte search of source lines."
            />
          ) : (
            <EmptyState icon={Type} title="Identifier search" detail="Search for an identifier, route path or config key. Source text is fetched only when you open a result." />
          )}
        </TabsContent>
      </Tabs>

      {!searched ? (
        <InlineNote>Search runs over this analysis only. Nothing is saved after the server restarts.</InlineNote>
      ) : null}
    </div>
  );
}

export default function SearchPage() {
  return (
    <RunGate title="Analyse a repository to search its code">
      <SearchBody />
    </RunGate>
  );
}
