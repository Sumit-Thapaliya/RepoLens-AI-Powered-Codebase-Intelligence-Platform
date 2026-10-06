"use client";

import * as React from "react";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  BrainCircuit,
  ChevronDown,
  CornerDownLeft,
  FileCode2,
  Info,
  Loader2,
  Route,
  Send,
  Sparkles,
  Trash2,
  Workflow as WorkflowIcon,
} from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { Markdown } from "@/components/common/markdown";
import { PathLink } from "@/components/common/path-link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, InlineNote, SkeletonCard, useToast } from "@/components/ui/states";
import { ApiError, askQuestion, getCapabilities, getChatHistory, getChatSuggestions } from "@/lib/api";
import type { Capabilities, ChatAnswer, ChatCitation } from "@/lib/types";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { cn } from "@/lib/utils";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  answer?: ChatAnswer;
  created_at?: string | null;
}

function TraceChain({ answer, onOpen }: { answer: ChatAnswer; onOpen: (path: string, line?: number | null) => void }) {
  const trace = answer.trace;
  if (!trace || !trace.steps?.length) return null;
  return (
    <div className="mt-3 rounded-lg border border-border bg-surface-muted/30 p-3">
      <p className="flex items-center gap-2 text-2xs uppercase tracking-wider text-muted-foreground">
        <WorkflowIcon className="size-3" /> Traced chain
        {trace.confidence ? <Badge variant="outline" className="font-normal">{Math.round(trace.confidence * 100)}%</Badge> : null}
      </p>
      <ol className="mt-2 space-y-1.5">
        {trace.steps.map((step, index) => (
          <li key={step.id ?? index} className="flex items-start gap-2">
            <span className="mono mt-0.5 w-4 shrink-0 text-right text-2xs text-muted-foreground">{index + 1}</span>
            <button
              type="button"
              disabled={!step.file_path}
              onClick={() => step.file_path && onOpen(step.file_path, step.line)}
              className={cn(
                "min-w-0 flex-1 rounded-md border border-border/70 px-2 py-1.5 text-left transition-colors",
                step.file_path && "hover:border-primary/50",
              )}
            >
              <span className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="font-normal">
                  {step.kind}
                </Badge>
                <span className="text-2xs font-medium">{step.label}</span>
              </span>
              {step.file_path ? (
                <span className="mono mt-0.5 block truncate text-2xs text-muted-foreground">
                  {step.file_path}
                  {step.line ? `:${step.line}` : ""}
                </span>
              ) : null}
            </button>
          </li>
        ))}
      </ol>
      {trace.truncated ? (
        <p className="mt-2 text-2xs text-amber-300">
          Trace truncated at the configured depth — deeper hops could not be resolved statically.
        </p>
      ) : null}
    </div>
  );
}

function CitationList({ citations, onOpen }: { citations: ChatCitation[]; onOpen: (path: string, line?: number | null) => void }) {
  const [open, setOpen] = React.useState(false);
  if (!citations.length) return null;
  const shown = open ? citations : citations.slice(0, 4);
  return (
    <div className="mt-3">
      <p className="flex items-center gap-2 text-2xs uppercase tracking-wider text-muted-foreground">
        <FileCode2 className="size-3" /> Sources ({citations.length})
      </p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {shown.map((citation, index) => (
          <button
            key={`${citation.path}-${index}`}
            type="button"
            onClick={() => onOpen(citation.path, citation.line)}
            className="path-chip max-w-full"
            title={citation.reason ?? undefined}
          >
            <FileCode2 className="size-3 shrink-0" />
            <span className="truncate">
              {citation.path}
              {citation.line ? `:${citation.line}` : ""}
            </span>
          </button>
        ))}
        {citations.length > 4 ? (
          <button type="button" className="text-2xs text-primary hover:underline" onClick={() => setOpen((value) => !value)}>
            {open ? "show less" : `+${citations.length - 4} more`}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function RetrievalDetails({ answer }: { answer: ChatAnswer }) {
  const [open, setOpen] = React.useState(false);
  if (!answer.retrieval?.length) return null;
  return (
    <div className="mt-3">
      <button
        type="button"
        className="flex items-center gap-1.5 text-2xs text-muted-foreground transition-colors hover:text-foreground"
        onClick={() => setOpen((value) => !value)}
      >
        <ChevronDown className={cn("size-3 transition-transform", open && "rotate-180")} />
        Retrieval evidence ({answer.retrieval.length} chunks,{" "}
        {answer.retrieval[0] ? `${(answer.retrieval[0].score * 100).toFixed(0)}% top score` : "n/a"})
      </button>
      {open ? (
        <ul className="mt-2 space-y-1.5">
          {answer.retrieval.slice(0, 10).map((hit) => (
            <li key={hit.id} className="rounded-md border border-border/70 px-2.5 py-1.5">
              <p className="mono truncate text-2xs" title={hit.path}>
                {hit.path}:{hit.start_line} · {hit.kind}
                {hit.symbol ? ` · ${hit.symbol}` : ""} · score {hit.score.toFixed(3)}
              </p>
              <p className="mt-0.5 line-clamp-2 text-2xs text-muted-foreground">{hit.snippet}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function ChatBody() {
  const { analysisId, analysis } = useAnalysisContext();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { push } = useToast();

  const focusPath = searchParams.get("path");

  const [messages, setMessages] = React.useState<Message[]>([]);
  const [suggestions, setSuggestions] = React.useState<string[]>([]);
  const [capabilities, setCapabilities] = React.useState<Capabilities | null>(null);
  const [question, setQuestion] = React.useState("");
  const [asking, setAsking] = React.useState(false);
  const [loadingHistory, setLoadingHistory] = React.useState(true);
  const [error, setError] = React.useState<ApiError | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!analysisId) return;
    (async () => {
      try {
        const [history, suggestionPayload, caps] = await Promise.all([
          getChatHistory(analysisId, 40),
          getChatSuggestions(analysisId),
          getCapabilities().catch(() => null),
        ]);
        setMessages(
          history.messages.map((message, index) => ({
            id: message.id ?? `history-${index}`,
            role: message.role === "user" ? "user" : "assistant",
            content: message.content,
            created_at: message.created_at,
          })),
        );
        setSuggestions(suggestionPayload.suggestions);
        setCapabilities(caps);
      } catch (cause) {
        setError(cause instanceof ApiError ? cause : new ApiError(String(cause)));
      } finally {
        setLoadingHistory(false);
      }
    })();
  }, [analysisId]);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, asking]);

  const send = React.useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!analysisId || !trimmed || asking) return;
      const history = messages.slice(-8).map((message) => ({ role: message.role, content: message.content }));
      setMessages((current) => [...current, { id: `u-${Date.now()}`, role: "user", content: trimmed }]);
      setQuestion("");
      setAsking(true);
      try {
        const answer = await askQuestion(analysisId, trimmed, history, focusPath);
        setMessages((current) => [
          ...current,
          { id: `a-${Date.now()}`, role: "assistant", content: answer.answer, answer },
        ]);
      } catch (cause) {
        const apiError = cause instanceof ApiError ? cause : new ApiError(String(cause));
        push({ tone: "error", title: "Question failed", detail: apiError.message });
        setMessages((current) => [
          ...current,
          {
            id: `e-${Date.now()}`,
            role: "assistant",
            content: `**Could not answer.** ${apiError.message}${apiError.hint ? `\n\n${apiError.hint}` : ""}`,
          },
        ]);
      } finally {
        setAsking(false);
      }
    },
    [analysisId, asking, messages, focusPath, push],
  );

  const openFile = (path: string, line?: number | null) =>
    router.push(`/explorer?path=${encodeURIComponent(path)}${line ? `&line=${line}` : ""}`);

  if (error && !messages.length && !loadingHistory) {
    return <ErrorState error={error} title="Could not load the conversation" className="m-6" />;
  }
  if (loadingHistory && !messages.length) return <SkeletonCard className="m-6" lines={10} />;

  return (
    <div className="flex h-[calc(100svh-7.5rem)] min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-2.5 lg:px-6">
        <div className="flex items-center gap-2">
          <BrainCircuit className="size-4 text-primary" />
          <span className="text-sm font-semibold">Ask this repository</span>
          {capabilities ? (
            <Badge variant={capabilities.llm.mode === "llm" ? "success" : "warning"} className="font-normal">
              {capabilities.llm.mode === "llm" ? `LLM: ${capabilities.llm.model ?? capabilities.llm.provider}` : "retrieval-only mode"}
            </Badge>
          ) : null}
          {focusPath ? (
            <Badge variant="info" className="mono font-normal">
              focused on {focusPath.split("/").pop()}
            </Badge>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {focusPath ? (
            <Button size="xs" variant="ghost" onClick={() => router.push("/chat")}>
              clear focus
            </Button>
          ) : null}
          {messages.length ? (
            <Button
              size="xs"
              variant="ghost"
              onClick={() => {
                setMessages([]);
                push({ tone: "info", title: "Cleared locally", detail: "Stored history remains available for this run." });
              }}
            >
              <Trash2 className="size-3" /> clear view
            </Button>
          ) : null}
        </div>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4 scrollbar-thin lg:px-6">
        {messages.length === 0 ? (
          <div className="mx-auto max-w-3xl">
            <EmptyState
              icon={Sparkles}
              title={`Ask anything about ${analysis?.branch ? "this snapshot" : "this repository"}`}
              detail="Answers are built from the stored analysis only: parsed symbols, the dependency graph, traced workflows, endpoints and database models. Every claim comes with the files it was derived from."
            />
            {suggestions.length ? (
              <div className="mt-2 flex flex-wrap justify-center gap-2">
                {suggestions.slice(0, 8).map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => void send(suggestion)}
                    className="rounded-full border border-border px-3 py-1.5 text-2xs text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-5">
            {messages.map((message) =>
              message.role === "user" ? (
                <div key={message.id} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-sm border border-primary/25 bg-primary/10 px-4 py-2.5">
                    <p className="text-sm">{message.content}</p>
                  </div>
                </div>
              ) : (
                <div key={message.id} className="rounded-xl border border-border bg-surface/70 p-4">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Badge variant={message.answer?.model && message.answer.model !== "retrieval-only" ? "success" : "secondary"} className="font-normal">
                      {message.answer?.model ?? "answer"}
                    </Badge>
                    {message.answer?.grounded ? (
                      <Badge variant="outline" className="font-normal">
                        grounded in analysis data
                      </Badge>
                    ) : null}
                    {message.answer?.intent ? (
                      <Badge variant="outline" className="font-normal">
                        intent: {message.answer.intent}
                      </Badge>
                    ) : null}
                    {message.answer?.evidence_count !== undefined ? (
                      <span className="text-2xs text-muted-foreground">{message.answer.evidence_count} evidence items</span>
                    ) : null}
                    {message.answer?.latency_ms ? (
                      <span className="text-2xs text-muted-foreground">· {message.answer.latency_ms} ms</span>
                    ) : null}
                  </div>

                  <Markdown content={message.content} />

                  {message.answer?.impact ? (
                    <div className="mt-3 rounded-lg border border-primary/25 bg-primary/5 p-3">
                      <p className="flex items-center gap-2 text-2xs uppercase tracking-wider text-primary">
                        <Route className="size-3" /> impact computed for {message.answer.impact.target}
                      </p>
                      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                        {[
                          { label: "Dependents", value: message.answer.impact.dependents.length },
                          { label: "Transitive", value: message.answer.impact.indirect_dependents.length },
                          { label: "Endpoints", value: message.answer.impact.affected_endpoints.length },
                          { label: "Tests", value: message.answer.impact.related_tests.length },
                        ].map((stat) => (
                          <div key={stat.label} className="rounded-md border border-border bg-surface-muted/40 px-2.5 py-1.5">
                            <p className="text-2xs text-muted-foreground">{stat.label}</p>
                            <p className="text-sm font-semibold tabular-nums">{stat.value}</p>
                          </div>
                        ))}
                      </div>
                      <Button
                        size="xs"
                        variant="outline"
                        className="mt-2"
                        onClick={() => router.push(`/impact?path=${encodeURIComponent(message.answer!.impact!.target)}`)}
                      >
                        Open full impact report
                      </Button>
                    </div>
                  ) : null}

                  {message.answer ? <TraceChain answer={message.answer} onOpen={openFile} /> : null}
                  {message.answer ? <CitationList citations={message.answer.citations} onOpen={openFile} /> : null}
                  {message.answer ? <RetrievalDetails answer={message.answer} /> : null}

                  {message.answer?.notes?.length ? (
                    <InlineNote className="mt-3 flex items-start gap-2">
                      <Info className="mt-0.5 size-3.5 shrink-0" />
                      <span>{message.answer.notes.join(" ")}</span>
                    </InlineNote>
                  ) : null}

                  {message.answer?.followups?.length ? (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {message.answer.followups.slice(0, 4).map((followup) => (
                        <button
                          key={followup}
                          type="button"
                          onClick={() => void send(followup)}
                          className="rounded-full border border-border px-2.5 py-1 text-2xs text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
                        >
                          {followup}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ),
            )}
            {asking ? (
              <div className="flex items-center gap-2 rounded-xl border border-border bg-surface/70 px-4 py-3 text-xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin text-primary" />
                Retrieving evidence from the stored analysis…
              </div>
            ) : null}
          </div>
        )}
      </div>

      <div className="border-t border-border bg-surface/50 px-4 py-3 lg:px-6">
        <form
          className="mx-auto flex max-w-3xl items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void send(question);
          }}
        >
          <Textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send(question);
              }
            }}
            placeholder={
              focusPath
                ? `Ask about ${focusPath.split("/").pop()} (e.g. what could break if I modify this?)`
                : "Ask about authentication, data models, a file, or what breaks if you change something…"
            }
            className="min-h-[42px] flex-1 py-2.5"
            rows={1}
          />
          <Button type="submit" loading={asking} disabled={!question.trim()} className="h-[42px]">
            <Send className="size-3.5" /> Ask
          </Button>
        </form>
        {suggestions.length && !asking ? (
          <div className="mx-auto mt-2 flex max-w-3xl flex-wrap gap-1.5">
            {suggestions.slice(0, 4).map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => void send(suggestion)}
                className="rounded-full border border-border px-2.5 py-1 text-2xs text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
              >
                {suggestion}
              </button>
            ))}
          </div>
        ) : null}
        <p className="mx-auto mt-1.5 flex max-w-3xl items-center gap-1.5 text-2xs text-muted-foreground">
          <CornerDownLeft className="size-3" /> Enter to send, Shift+Enter for a new line.
          {capabilities && capabilities.llm.mode !== "llm" ? (
            <span>
              No LLM key configured, so answers are composed by the extractive engine and always cite their sources.
            </span>
          ) : null}
        </p>
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <RunGate title="Analyse a repository to ask questions about it">
      <Suspense fallback={<SkeletonCard className="m-6" lines={8} />}>
        <ChatBody />
      </Suspense>
    </RunGate>
  );
}
