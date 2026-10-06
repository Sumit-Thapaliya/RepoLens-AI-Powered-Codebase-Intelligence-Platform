"use client";

import * as React from "react";
import { BookOpen, Download, FileJson, Loader2, RefreshCw, Server, Sparkles } from "lucide-react";
import { RunGate } from "@/components/app/run-gate";
import { Markdown } from "@/components/common/markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ErrorState, InlineNote, SkeletonCard, useToast } from "@/components/ui/states";
import { ApiError, generateDoc, getBundle, getCapabilities, getDoc } from "@/lib/api";
import type { Capabilities, DocumentPayload } from "@/lib/types";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { formatBytes } from "@/lib/hooks";

const KINDS = [
  { id: "readme", label: "Repository overview", detail: "What the project is, how it is structured, how to run it" },
  { id: "api", label: "API reference", detail: "Every detected endpoint with handler, auth and source location" },
  { id: "onboarding", label: "Onboarding guide", detail: "Where to start reading the code and what to change first" },
];

function DocsBody() {
  const { analysisId, repo, analysis } = useAnalysisContext();
  const { push } = useToast();
  const [kind, setKind] = React.useState("readme");
  const [documents, setDocuments] = React.useState<Record<string, DocumentPayload>>({});
  const [capabilities, setCapabilities] = React.useState<Capabilities | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [regenerating, setRegenerating] = React.useState(false);
  const [useLlm, setUseLlm] = React.useState(true);
  const [error, setError] = React.useState<ApiError | null>(null);
  const [bundleLoading, setBundleLoading] = React.useState(false);

  const current = documents[kind];

  const load = React.useCallback(
    async (target: string) => {
      if (!analysisId) return;
      setLoading(true);
      setError(null);
      try {
        const [doc, caps] = await Promise.all([getDoc(analysisId, target), getCapabilities().catch(() => null)]);
        setDocuments((current) => ({ ...current, [target]: doc }));
        setCapabilities(caps);
      } catch (cause) {
        setError(cause instanceof ApiError ? cause : new ApiError(String(cause)));
      } finally {
        setLoading(false);
      }
    },
    [analysisId],
  );

  React.useEffect(() => {
    void load(kind);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId, kind]);

  const regenerate = async () => {
    if (!analysisId) return;
    setRegenerating(true);
    try {
      const doc = await generateDoc(analysisId, kind, useLlm && capabilities?.llm.configured === true);
      setDocuments((current) => ({ ...current, [kind]: doc }));
      push({
        tone: "success",
        title: "Document regenerated",
        detail: doc.generated_by === "llm" ? "Polished by the configured LLM from the deterministic draft." : "Produced by the deterministic analyser.",
      });
    } catch (cause) {
      push({ tone: "error", title: "Regeneration failed", detail: cause instanceof Error ? cause.message : String(cause) });
    } finally {
      setRegenerating(false);
    }
  };

  const downloadMarkdown = () => {
    if (!current) return;
    const blob = new Blob([current.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `repolens-${kind}-${analysisId}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const downloadBundle = async () => {
    if (!analysisId) return;
    setBundleLoading(true);
    try {
      const bundle = await getBundle(analysisId);
      const text = JSON.stringify(bundle, null, 2);
      const blob = new Blob([text], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `repolens-bundle-${analysisId}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      push({ tone: "success", title: "Bundle exported", detail: `${formatBytes(text.length)} of JSON written to your downloads.` });
    } catch (cause) {
      push({ tone: "error", title: "Export failed", detail: cause instanceof Error ? cause.message : String(cause) });
    } finally {
      setBundleLoading(false);
    }
  };

  if (loading && !current) return <SkeletonCard className="m-6" lines={12} />;
  if (error && !current) return <ErrorState error={error} onRetry={() => void load(kind)} className="m-6" />;

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-base font-semibold tracking-tight">Reports & export</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Deterministic documents generated from this analysis
            {repo ? ` for ${repo.full_name}@${analysis?.commit_sha?.slice(0, 7) ?? analysis?.branch ?? ""}` : ""}. They can
            optionally be polished by the configured LLM — the draft always comes from the stored artefacts.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex cursor-pointer items-center gap-2 text-2xs text-muted-foreground">
            <input
              type="checkbox"
              checked={useLlm}
              disabled={!capabilities?.llm.configured}
              onChange={(event) => setUseLlm(event.target.checked)}
              className="accent-[hsl(var(--primary))]"
            />
            use LLM polish
            {!capabilities?.llm.configured ? " (no key configured)" : ""}
          </label>
          <Button variant="outline" size="sm" loading={regenerating} onClick={() => void regenerate()}>
            <RefreshCw /> Regenerate
          </Button>
          <Button variant="outline" size="sm" onClick={downloadMarkdown} disabled={!current}>
            <Download /> Markdown
          </Button>
          <Button variant="outline" size="sm" loading={bundleLoading} onClick={() => void downloadBundle()}>
            <FileJson /> Full JSON bundle
          </Button>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <section className="panel overflow-hidden">
          <Tabs value={kind} onValueChange={setKind}>
            <div className="panel-header">
              <TabsList>
                {KINDS.map((entry) => (
                  <TabsTrigger key={entry.id} value={entry.id}>
                    <BookOpen className="size-3" /> {entry.label}
                  </TabsTrigger>
                ))}
              </TabsList>
              {current ? (
                <span className="text-2xs text-muted-foreground">
                  {(current.markdown.length / 1024).toFixed(1)} KB · generated by {current.generated_by}
                </span>
              ) : null}
            </div>
            <div className="max-h-[70vh] overflow-y-auto p-5 scrollbar-thin">
              {KINDS.map((entry) => (
                <TabsContent key={entry.id} value={entry.id} className="mt-0">
                  {documents[entry.id] ? (
                    <Markdown content={documents[entry.id].markdown} />
                  ) : (
                    <p className="flex items-center gap-2 py-10 text-xs text-muted-foreground">
                      <Loader2 className="size-3.5 animate-spin" /> Loading document…
                    </p>
                  )}
                </TabsContent>
              ))}
            </div>
          </Tabs>
        </section>

        <div className="space-y-4">
          <section className="panel">
            <div className="panel-header">
              <span className="panel-title">What powers this analysis</span>
            </div>
            <ul className="divide-y divide-border text-xs">
              {capabilities ? (
                <>
                  <li className="flex items-center justify-between gap-3 px-5 py-2.5">
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <Sparkles className="size-3.5" /> LLM
                    </span>
                    <span className="text-right">
                      <span className="block">{capabilities.llm.provider}</span>
                      <span className="text-2xs text-muted-foreground">{capabilities.llm.mode}</span>
                    </span>
                  </li>
                  <li className="flex items-center justify-between gap-3 px-5 py-2.5">
                    <span className="text-muted-foreground">Embeddings</span>
                    <span className="text-right">
                      <span className="block">{capabilities.embeddings.provider}</span>
                      <span className="text-2xs text-muted-foreground">dim {capabilities.embeddings.dim}</span>
                    </span>
                  </li>
                  <li className="flex items-center justify-between gap-3 px-5 py-2.5">
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <Server className="size-3.5" /> Database
                    </span>
                    <span className="text-right">
                      <span className="block">{capabilities.database.dialect}</span>
                      <span className="text-2xs text-muted-foreground">
                        {capabilities.database.pgvector ? "pgvector enabled" : "vector ranking in process"}
                      </span>
                    </span>
                  </li>
                  <li className="flex items-center justify-between gap-3 px-5 py-2.5">
                    <span className="text-muted-foreground">GitHub API</span>
                    <span className="text-right">
                      <span className="block">{capabilities.github.authenticated ? "authenticated" : "anonymous"}</span>
                      <span className="text-2xs text-muted-foreground">{capabilities.github.rate_limit}</span>
                    </span>
                  </li>
                </>
              ) : (
                <li className="px-5 py-4 text-muted-foreground">Capabilities unavailable.</li>
              )}
            </ul>
            <div className="border-t border-border p-4">
              <InlineNote>{capabilities?.llm.note ?? "LLM status unknown."}</InlineNote>
              <InlineNote className="mt-2">{capabilities?.database.note ?? ""}</InlineNote>
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <span className="panel-title">Limits in effect</span>
              <Badge variant="outline" className="font-normal">
                env configurable
              </Badge>
            </div>
            <ul className="divide-y divide-border text-xs">
              {capabilities
                ? Object.entries(capabilities.limits).map(([key, value]) => (
                    <li key={key} className="flex items-center justify-between px-5 py-2">
                      <span className="text-muted-foreground">{key.replace(/_/g, " ")}</span>
                      <span className="tabular-nums">{typeof value === "number" ? value.toLocaleString() : String(value)}</span>
                    </li>
                  ))
                : null}
            </ul>
          </section>

          <InlineNote>
            The JSON bundle contains every stored artefact for this run — overview, architecture, endpoints, database,
            workflows, dependencies, quality, frameworks and manifests — so you can diff two analyses offline or feed them
            into CI.
          </InlineNote>
        </div>
      </div>
    </div>
  );
}

export default function DocsPage() {
  return (
    <RunGate title="Analyse a repository to generate reports">
      <DocsBody />
    </RunGate>
  );
}
