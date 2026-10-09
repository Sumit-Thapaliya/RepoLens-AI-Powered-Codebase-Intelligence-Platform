"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { FileSearch, Filter, Search as SearchIcon, Sparkles, Type } from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, ErrorState, InlineNote, SkeletonCard } from "@/components/ui/states";
import { ApiError, getChatSuggestions, getCapabilities, grep, search as semanticSearch } from "@/lib/api";
import type { Capabilities, SearchHit } from "@/lib/types";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { cn } from "@/lib/utils";

const EXAMPLE_QUERIES = [
  "password hashing and token creation",
  "how requests are authenticated",
  "database session management",
  "configuration and environment settings",
  "background/email sending",
];

interface GrepMatch {
  path: string;
  line: number;
  text: string;
  kind?: string;
}

function SearchBody() {
  const { analysisId } = useAnalysisContext();
  const router = useRouter();
  const [tab, setTab] = React.useState("semantic");
  const [query, setQuery] = React.useState("");
  const [hits, setHits] = React.useState<SearchHit[]>([]);
  const [matches, setMatches] = React.useState<GrepMatch[]>([]);
  const [backend, setBackend] = React.useState<{ backend?: string; embedding?: { provider: string; neural: boolean } }>({});
  const [capabilities, setCapabilities] = React.useState<Capabilities | null>(null);
  const [suggestions, setSuggestions] = React.useState<string[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<ApiError | null>(null);
  const [searched, setSearched] = React.useState(false);

  React.useEffect(() => {
    if (!analysisId) return;
    getCapabilities().then(setCapabilities).catch(() => setCapabilities(null));
    getChatSuggestions(analysisId)
      .then((payload) => setSuggestions(payload.suggestions))
      .catch(() => setSuggestions([]));
  }, [analysisId]);

  const runSearch = React.useCallback(
    async (text: string, mode = tab) => {
      const trimmed = text.trim();
      if (!analysisId || !trimmed) return;
      setLoading(true);
      setError(null);
      setSearched(true);
      try {
        if (mode === "semantic") {
          const payload = await semanticSearch(analysisId, trimmed, 20);
          setHits(payload.hits);
          setBackend({ backend: payload.backend, embedding: payload.embedding });
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
    [analysisId, tab],
  );

  const open = (path: string, line?: number | null) =>
    router.push(`/explorer?path=${encodeURIComponent(path)}${line ? `&line=${line}` : ""}`);

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-base font-semibold tracking-tight">Search</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Two indexes over the stored analysis: a semantic search across code chunks, and an exact text search for
            identifiers and strings.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {capabilities ? (
            <>
              <Badge variant={capabilities.embeddings.neural ? "success" : "warning"} className="font-normal">
                embeddings: {capabilities.embeddings.provider}
                {capabilities.embeddings.neural ? "" : " (lexical blend)"}
              </Badge>
              <Badge variant="outline" className="font-normal">
                vector store: {capabilities.database.pgvector ? "pgvector" : "in-process cosine"}
              </Badge>
            </>
          ) : null}
        </div>
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
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={tab === "semantic" ? "Describe what you are looking for…" : "Exact text, e.g. get_user_by_email"}
            className="h-10 pl-9"
          />
        </div>
        <Tabs value={tab} onValueChange={(value) => { setTab(value); if (query) void runSearch(query, value); }}>
          <TabsList className="h-10">
            <TabsTrigger value="semantic" className="h-8">
              <Sparkles className="size-3" /> Semantic
            </TabsTrigger>
            <TabsTrigger value="text" className="h-8">
              <Type className="size-3" /> Exact text
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
              void runSearch(example, "semantic");
              setTab("semantic");
            }}
          >
            {example}
          </button>
        ))}
      </div>

      {error ? <ErrorState error={error} onRetry={() => void runSearch(query)} /> : null}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsContent value="semantic" className="mt-0">
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
                        <span className="text-2xs tabular-nums text-muted-foreground">score {hit.score.toFixed(3)}</span>
                      </span>
                    </div>
                    <pre className="mono mt-2 max-h-40 overflow-hidden whitespace-pre-wrap break-words rounded-lg border border-border bg-surface-muted/50 p-3 text-[0.72rem] leading-relaxed text-muted-foreground">
                      {hit.snippet}
                    </pre>
                  </button>
                </li>
              ))}
            </ul>
          ) : searched ? (
            <EmptyState
              icon={FileSearch}
              title="No chunk matched"
              detail="Try a different phrasing, or switch to Exact text to search identifiers verbatim. Semantic scores blend vector similarity with lexical overlap when no neural embedding key is configured."
            />
          ) : (
            <EmptyState icon={Sparkles} title="Semantic search" detail="Describe the behaviour you are looking for; results point at concrete chunks with their file and line." />
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
                    <p className="mono mt-1 line-clamp-2 text-2xs text-muted-foreground">{match.text}</p>
                  </button>
                </li>
              ))}
            </ul>
          ) : searched ? (
            <EmptyState icon={Type} title={`No occurrence of “${query}”`} detail="Exact text search runs over parsed file contents and stored docs for this run only." />
          ) : (
            <EmptyState icon={Type} title="Exact text search" detail="Search for an identifier, route path or config key verbatim." />
          )}
        </TabsContent>
      </Tabs>

      {suggestions.length && !searched ? (
        <InlineNote>
          Generated questions for this repository that the AI chat can answer:{" "}
          {suggestions.slice(0, 4).join(" · ")}
        </InlineNote>
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
