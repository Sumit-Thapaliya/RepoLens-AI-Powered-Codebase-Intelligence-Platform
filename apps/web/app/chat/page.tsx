"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  ArrowUp,
  BookOpenText,
  Check,
  CircleHelp,
  Clock3,
  Database,
  FileCode2,
  MessageSquareText,
  Plus,
  ShieldCheck,
  Sparkles,
  Zap,
} from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { ApiError, chatWithRepository, getRagChatStatus } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import type { RagCitation } from "@/lib/types";
import { cn } from "@/lib/utils";

const EXAMPLES = [
  "Where is authentication enforced?",
  "Trace a request from the route to storage.",
  "How is configuration loaded?",
  "Which modules are most important to understand first?",
];

type Turn = {
  role: "user" | "assistant";
  content: string;
  citations?: RagCitation[];
};

function CitationButton({ citation, onOpen }: { citation: RagCitation; onOpen: (citation: RagCitation) => void }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(citation)}
      className="group inline-flex max-w-full items-center gap-2 rounded-lg border border-border/80 bg-surface-muted/65 px-2.5 py-1.5 text-left transition-colors hover:border-primary/45 hover:bg-primary/5"
      title={`Open ${citation.path} in Code Explorer`}
    >
      <span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-primary/10 font-mono text-[9px] font-semibold text-primary">
        {citation.id}
      </span>
      <span className="min-w-0">
        <span className="mono block truncate text-[10px] leading-4 text-foreground/85">{citation.path}</span>
        <span className="block text-[9px] leading-3 text-muted-foreground">
          {citation.symbol ? `${citation.symbol} · ` : ""}lines {citation.start_line}–{citation.end_line}
        </span>
      </span>
      <FileCode2 className="ml-1 size-3 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
    </button>
  );
}

function ChatMessage({ turn, onOpenCitation }: { turn: Turn; onOpenCitation: (citation: RagCitation) => void }) {
  const isUser = turn.role === "user";
  return (
    <article className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-xl border",
          isUser
            ? "border-primary/20 bg-primary/10 text-primary"
            : "border-accent/25 bg-accent/10 text-accent",
        )}
        aria-hidden="true"
      >
        {isUser ? <span className="text-xs font-semibold">Y</span> : <Sparkles className="size-4" />}
      </div>
      <div className={cn("min-w-0 max-w-[88%] sm:max-w-[82%]", isUser && "text-right")}>
        <div className={cn("mb-1 flex items-center gap-2 text-[10px] text-muted-foreground", isUser && "justify-end")}>
          <span className="font-medium text-foreground/80">{isUser ? "You" : "RepoLens"}</span>
          {!isUser ? <span>grounded answer</span> : null}
        </div>
        <div
          className={cn(
            "rounded-2xl border px-4 py-3 text-[13px] leading-6",
            isUser
              ? "rounded-tr-md border-primary/20 bg-primary/[0.075] text-foreground"
              : "rounded-tl-md border-border/80 bg-surface-muted/60 text-foreground/90",
          )}
        >
          <p className="whitespace-pre-wrap break-words">{turn.content}</p>
        </div>
        {!isUser && turn.citations?.length ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {turn.citations.map((citation) => (
              <CitationButton key={`${citation.id}-${citation.path}`} citation={citation} onOpen={onOpenCitation} />
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function SetupNotice({
  enabled,
  stale,
  message,
  onRetry,
}: {
  enabled: boolean;
  stale: boolean;
  message?: string | null;
  onRetry: () => void;
}) {
  if (enabled && !stale && message?.includes("temporarily unavailable")) {
    return (
      <div className="mx-auto max-w-lg rounded-2xl border border-amber-500/25 bg-amber-500/[0.06] p-6 text-center">
        <AlertCircle className="mx-auto size-6 text-amber-400" />
        <h2 className="mt-3 text-sm font-semibold">Chat storage is unavailable</h2>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{message}</p>
        <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}>Try again</Button>
      </div>
    );
  }

  if (!enabled) {
    return (
      <div className="mx-auto max-w-lg rounded-2xl border border-border/80 bg-surface/75 p-6 text-center shadow-card sm:p-8">
        <div className="mx-auto flex size-12 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
          <Zap className="size-5" />
        </div>
        <h2 className="mt-4 text-sm font-semibold">AI chat needs server setup</h2>
        <p className="mx-auto mt-2 max-w-md text-xs leading-5 text-muted-foreground">
          Add a Neon PostgreSQL URL and an OpenAI-compatible API key to the API service. Keep both values server-side;
          static analysis and keyword search continue to work without them.
        </p>
        <div className="mt-4 flex flex-wrap justify-center gap-1.5">
          <Badge variant="outline" className="font-mono">RAG_DATABASE_URL</Badge>
          <Badge variant="outline" className="font-mono">RAG_API_KEY</Badge>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg rounded-2xl border border-border/80 bg-surface/75 p-6 text-center shadow-card sm:p-8">
      <div className="mx-auto flex size-12 items-center justify-center rounded-2xl border border-accent/25 bg-accent/10 text-accent">
        {stale ? <Clock3 className="size-5" /> : <BookOpenText className="size-5" />}
      </div>
      <h2 className="mt-4 text-sm font-semibold">
        {stale ? "Refresh the chat index" : "This commit is not indexed yet"}
      </h2>
      <p className="mx-auto mt-2 max-w-md text-xs leading-5 text-muted-foreground">
        {message || "Run a fresh repository analysis after RAG has been configured. RepoLens will create a bounded vector index for this commit."}
      </p>
    </div>
  );
}

function ChatBody() {
  const { analysisId, analysis, repo } = useAnalysisContext();
  const router = useRouter();
  const { data: status, error: statusError, isLoading: statusLoading, mutate } = useApi(
    analysisId ? `rag-chat-status:${analysisId}` : null,
    () => getRagChatStatus(analysisId!),
  );
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [draft, setDraft] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const [requestError, setRequestError] = React.useState<string | null>(null);
  const transcriptRef = React.useRef<HTMLDivElement>(null);
  const composerRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    setTurns([]);
    setDraft("");
    setRequestError(null);
  }, [analysisId]);

  React.useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, pending]);

  const openCitation = (citation: RagCitation) => {
    router.push(`/explorer?path=${encodeURIComponent(citation.path)}&line=${citation.start_line}`);
  };

  const send = async (suggestion?: string) => {
    const question = (suggestion ?? draft).trim();
    if (!analysisId || !question || pending || !status?.enabled || !status.indexed) return;
    const history = turns.slice(-8).map(({ role, content }) => ({ role, content }));
    setTurns((current) => [...current, { role: "user", content: question }]);
    setDraft("");
    setPending(true);
    setRequestError(null);
    try {
      const result = await chatWithRepository(analysisId, question, history);
      setTurns((current) => [...current, { role: "assistant", content: result.answer, citations: result.citations }]);
    } catch (cause) {
      setRequestError(cause instanceof ApiError ? cause.message : "The chat request could not be completed. Try again.");
    } finally {
      setPending(false);
      composerRef.current?.focus();
    }
  };

  const indexed = Boolean(status?.enabled && status.indexed);
  const stateMessage = status?.message || null;
  const headerLabel = statusLoading
    ? "Checking index"
    : statusError
      ? "Status unavailable"
      : indexed
        ? "Ready to chat"
        : status?.enabled
          ? status.stale ? "Index needs refresh" : "Index not ready"
          : "Setup required";

  return (
    <div className="mx-auto max-w-7xl space-y-5 px-4 py-5 sm:px-6 sm:py-7">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-start gap-3.5">
          <div className="mt-0.5 flex size-11 shrink-0 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary shadow-[0_0_24px_hsl(var(--primary)/0.08)]">
            <MessageSquareText className="size-5" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-semibold tracking-tight sm:text-xl">Ask this codebase</h1>
              <Badge variant={indexed ? "success" : status?.enabled ? "warning" : "outline"}>
                {indexed ? <Check /> : <CircleHelp />}{headerLabel}
              </Badge>
            </div>
            <p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">
              Ask questions in plain language. Answers are grounded in retrieved files and link back to the exact source ranges.
            </p>
          </div>
        </div>
        {repo ? (
          <div className="flex items-center gap-2 rounded-lg border border-border/80 bg-surface/55 px-3 py-2">
            <FileCode2 className="size-3.5 text-primary" />
            <span className="mono max-w-[260px] truncate text-[11px]">{repo.full_name}</span>
            {analysis?.commit_sha ? (
              <span className="mono rounded bg-surface-muted px-1.5 py-0.5 text-[9px] text-muted-foreground">
                {analysis.commit_sha.slice(0, 7)}
              </span>
            ) : null}
          </div>
        ) : null}
      </header>

      {statusError ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-amber-500/25 bg-amber-500/[0.05] px-3.5 py-2.5">
          <p className="text-xs text-muted-foreground">Could not read the chat index status: {statusError.message}</p>
          <Button variant="outline" size="xs" onClick={() => void mutate()}>Retry</Button>
        </div>
      ) : null}

      <div className="grid min-h-[min(72vh,780px)] gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
        <section className="panel flex min-h-[620px] flex-col overflow-hidden xl:min-h-0" aria-label="Repository chat">
          <div className="panel-header min-h-[54px]">
            <div className="flex min-w-0 items-center gap-2.5">
              <div className="flex size-7 items-center justify-center rounded-lg bg-accent/10 text-accent">
                <Sparkles className="size-3.5" />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold">Repository assistant</p>
                <p className="truncate text-[10px] text-muted-foreground">{repo?.full_name || "Current analysis"}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {indexed ? <Badge variant="outline" className="hidden sm:inline-flex">{status?.chunk_count} source excerpts</Badge> : null}
              {turns.length > 0 ? (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="Start a new chat"
                  aria-label="Start a new chat"
                  disabled={pending}
                  onClick={() => { setTurns([]); setRequestError(null); }}
                >
                  <Plus className="size-4" />
                </Button>
              ) : null}
            </div>
          </div>

          {statusLoading ? (
            <div className="flex flex-1 items-center justify-center">
              <div className="flex items-center gap-2 text-xs text-muted-foreground"><span className="size-2 animate-pulse rounded-full bg-primary" />Checking the repository index…</div>
            </div>
          ) : statusError ? (
            <div className="flex flex-1 items-center justify-center p-6">
              <div className="mx-auto max-w-lg rounded-2xl border border-amber-500/25 bg-amber-500/[0.06] p-6 text-center">
                <AlertCircle className="mx-auto size-6 text-amber-400" />
                <h2 className="mt-3 text-sm font-semibold">Chat status is unavailable</h2>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">{statusError.message}</p>
                <Button variant="outline" size="sm" className="mt-4" onClick={() => void mutate()}>Try again</Button>
              </div>
            </div>
          ) : indexed ? (
            <>
              <div ref={transcriptRef} className="flex-1 space-y-6 overflow-y-auto p-4 sm:p-6 scrollbar-thin" aria-live="polite">
                {turns.length === 0 ? (
                  <div className="flex min-h-[390px] flex-col items-center justify-center py-8 text-center">
                    <div className="grid-lines relative mb-5 flex size-[76px] items-center justify-center overflow-hidden rounded-[24px] border border-primary/20 bg-primary/[0.055] text-primary">
                      <span className="absolute inset-0 bg-gradient-to-br from-primary/10 via-transparent to-accent/10" />
                      <Sparkles className="relative size-7" />
                    </div>
                    <h2 className="text-sm font-semibold">What would you like to understand?</h2>
                    <p className="mt-1.5 max-w-sm text-xs leading-5 text-muted-foreground">
                      Ask about a flow, a symbol, an architectural choice, or where a behavior lives.
                    </p>
                    <div className="mt-6 grid w-full max-w-2xl gap-2 sm:grid-cols-2">
                      {EXAMPLES.map((example) => (
                        <button
                          key={example}
                          type="button"
                          disabled={pending}
                          onClick={() => void send(example)}
                          className="group flex min-h-12 items-center justify-between gap-3 rounded-xl border border-border/80 bg-surface-muted/40 px-3.5 py-2.5 text-left text-[11px] text-muted-foreground transition-all hover:border-primary/35 hover:bg-primary/[0.035] hover:text-foreground disabled:opacity-50"
                        >
                          <span>{example}</span><ArrowUp className="size-3.5 shrink-0 -rotate-45 text-muted-foreground/55 transition-colors group-hover:text-primary" />
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  turns.map((turn, index) => (
                    <ChatMessage key={`${turn.role}-${index}`} turn={turn} onOpenCitation={openCitation} />
                  ))
                )}
                {pending ? (
                  <div className="flex gap-3" role="status" aria-label="Generating answer">
                    <div className="mt-0.5 flex size-8 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 text-accent"><Sparkles className="size-4 animate-pulse" /></div>
                    <div className="rounded-2xl rounded-tl-md border border-border/80 bg-surface-muted/60 px-4 py-3">
                      <div className="flex items-center gap-2 text-xs text-muted-foreground"><span className="flex gap-1"><i className="size-1 animate-bounce rounded-full bg-primary" /><i className="size-1 animate-bounce rounded-full bg-primary [animation-delay:120ms]" /><i className="size-1 animate-bounce rounded-full bg-primary [animation-delay:240ms]" /></span>Searching relevant code…</div>
                    </div>
                  </div>
                ) : null}
                <div className="h-1" />
              </div>

              <div className="border-t border-border/80 bg-surface/55 p-3 sm:p-4">
                {requestError ? (
                  <div className="mb-2 flex items-start gap-2 rounded-lg border border-destructive/25 bg-destructive/[0.045] px-3 py-2 text-[11px] text-destructive">
                    <AlertCircle className="mt-0.5 size-3.5 shrink-0" /><span>{requestError}</span>
                  </div>
                ) : null}
                <form
                  className="rounded-xl border border-border bg-surface-muted/65 p-2 shadow-inner transition-colors focus-within:border-primary/40"
                  onSubmit={(event) => { event.preventDefault(); void send(); }}
                >
                  <Textarea
                    ref={composerRef}
                    value={draft}
                    onChange={(event) => setDraft(event.target.value.slice(0, 1_200))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        void send();
                      }
                    }}
                    maxLength={1_200}
                    rows={2}
                    disabled={pending}
                    placeholder="Ask anything about the code…"
                    aria-label="Ask a question about this repository"
                    className="min-h-[56px] border-0 bg-transparent px-2 py-1.5 text-xs leading-5 shadow-none focus-visible:ring-0"
                  />
                  <div className="flex items-center justify-between gap-2 px-1 pt-1">
                    <p className="flex items-center gap-1.5 text-[9px] text-muted-foreground/80">
                      <span><kbd className="rounded border border-border px-1 py-0.5 font-mono">Enter</kbd> to send</span>
                      <span className="hidden sm:inline">·</span>
                      <span className="hidden sm:inline"><kbd className="rounded border border-border px-1 py-0.5 font-mono">Shift + Enter</kbd> for a new line</span>
                    </p>
                    <Button type="submit" size="sm" className="h-8 gap-1.5 px-3" loading={pending} disabled={!draft.trim()}>
                      Ask <ArrowUp className="size-3" />
                    </Button>
                  </div>
                </form>
                <p className="mt-2 text-center text-[9px] leading-4 text-muted-foreground/75">
                  AI responses can be incomplete. Verify important details in the linked source excerpts.
                </p>
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center p-5 sm:p-8">
              <SetupNotice
                enabled={Boolean(status?.enabled)}
                stale={Boolean(status?.stale)}
                message={stateMessage}
                onRetry={() => void mutate()}
              />
            </div>
          )}
        </section>

        <aside className="flex flex-col gap-3">
          <section className="panel p-4">
            <div className="flex items-center gap-2">
              <div className="flex size-7 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400"><ShieldCheck className="size-3.5" /></div>
              <div>
                <h2 className="text-xs font-semibold">Evidence index</h2>
                <p className="text-[10px] text-muted-foreground">This analysis snapshot</p>
              </div>
            </div>
            <div className="mt-4 space-y-3">
              <div className="flex items-center justify-between gap-3 text-[11px]">
                <span className="text-muted-foreground">Index status</span>
                <span className={cn("inline-flex items-center gap-1.5 font-medium", indexed ? "text-emerald-400" : "text-amber-400")}>
                  <span className={cn("size-1.5 rounded-full", indexed ? "bg-emerald-400" : "bg-amber-400")} />
                  {indexed ? "Ready" : statusLoading ? "Checking" : "Not ready"}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 text-[11px]">
                <span className="text-muted-foreground">Source excerpts</span>
                <span className="mono text-[10px]">{indexed ? status?.chunk_count : "—"}</span>
              </div>
              <div className="flex items-center justify-between gap-3 text-[11px]">
                <span className="text-muted-foreground">Files represented</span>
                <span className="mono text-[10px]">{indexed ? status?.file_count : "—"}</span>
              </div>
              <div className="flex items-start justify-between gap-3 text-[11px]">
                <span className="shrink-0 text-muted-foreground">Commit</span>
                <span className="mono break-all text-right text-[9px] text-foreground/80">{analysis?.commit_sha?.slice(0, 12) || "—"}</span>
              </div>
              {status?.indexed_at && indexed ? (
                <div className="flex items-center justify-between gap-3 text-[10px]">
                  <span className="text-muted-foreground">Indexed</span>
                  <span className="text-right text-foreground/70">{new Date(status.indexed_at).toLocaleDateString()}</span>
                </div>
              ) : null}
            </div>
          </section>

          <section className="panel p-4">
            <div className="flex items-center gap-2">
              <Database className="size-3.5 text-primary" />
              <h2 className="text-xs font-semibold">How chat works</h2>
            </div>
            <ol className="mt-3 space-y-2.5">
              {[
                "Search the vector index for matching code excerpts.",
                "Send only the selected excerpts and your prompt to the server-side model.",
                "Return an answer with links to the source lines used.",
              ].map((step, index) => (
                <li key={step} className="flex gap-2.5 text-[10px] leading-4 text-muted-foreground">
                  <span className="flex size-4 shrink-0 items-center justify-center rounded-full border border-primary/20 bg-primary/[0.06] font-mono text-[9px] text-primary">{index + 1}</span>
                  {step}
                </li>
              ))}
            </ol>
          </section>

          <section className="rounded-xl border border-primary/15 bg-primary/[0.035] p-3.5">
            <div className="flex items-start gap-2.5">
              <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-primary" />
              <div>
                <h2 className="text-[10px] font-semibold">Privacy & retention</h2>
                <p className="mt-1 text-[10px] leading-4 text-muted-foreground">
                  When enabled, Neon stores a capped set of source excerpts and vectors for the latest two indexed commits. Chat history stays in this tab; recent turns are sent with each prompt and are not saved by RepoLens.
                </p>
              </div>
            </div>
          </section>

          <div className="flex items-center justify-center gap-1.5 px-2 text-[9px] text-muted-foreground/75">
            <Zap className="size-3 text-primary" />Fast retrieval · <Database className="size-3 text-primary" />Neon pgvector
          </div>
        </aside>
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <RunGate title="Analyze a repository to start a code chat">
      <ChatBody />
    </RunGate>
  );
}
