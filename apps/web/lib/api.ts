import type {
  Analysis,
  Capabilities,
  ChatAnswer,
  DatabasePayload,
  DependenciesPayload,
  DocumentPayload,
  Endpoint,
  EndpointPayload,
  FileNode,
  FilePayload,
  FrameworkInfo,
  ImpactReport,
  Overview,
  QualityPayload,
  RepoMetadata,
  RepoSummary,
  SearchHit,
  SymbolInfo,
  Workflow,
  WorkflowsPayload,
  ArchitectureGraph,
  Insight,
} from "./types";

/** Same-origin proxy configured in next.config.mjs (rewrites /backend/* -> FastAPI). */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/backend";

export class ApiError extends Error {
  code: string;
  status: number;
  hint?: string | null;
  detail?: unknown;
  requestId?: string | null;

  constructor(message: string, options: { code?: string; status?: number; hint?: string | null; detail?: unknown; requestId?: string | null } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = options.code ?? "request_failed";
    this.status = options.status ?? 0;
    this.hint = options.hint ?? null;
    this.detail = options.detail;
    this.requestId = options.requestId ?? null;
  }
}

type RequestOptions = Omit<RequestInit, "body"> & { body?: unknown; query?: Record<string, string | number | boolean | undefined | null> };

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, query, headers, ...rest } = options;
  let url = `${API_BASE}${path}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
    }
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...rest,
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(headers || {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch (cause) {
    throw new ApiError("Cannot reach the RepoLens API.", {
      code: "network_error",
      hint: "The API service may be down. Check that the backend is running and reachable.",
      detail: String(cause),
    });
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const envelope = (payload as { error?: { code?: string; message?: string; hint?: string; detail?: unknown }; request_id?: string }) ?? {};
    const error = envelope.error;
    throw new ApiError(error?.message || `Request failed with status ${response.status}`, {
      code: error?.code ?? `http_${response.status}`,
      status: response.status,
      hint: error?.hint,
      detail: error?.detail ?? payload,
      requestId: envelope.request_id,
    });
  }

  return payload as T;
}

/* ------------------------------------------------------------------ system */

export const getHealth = () => apiRequest<{ status: string; version: string; database: { status: string; dialect: string } }>("/health");
export const getCapabilities = () => apiRequest<Capabilities>("/system/capabilities");
export interface LanguageSupportPayload {
  deep_analysis: { language: string; label: string; parser: string; available: boolean }[];
  indexed_only: { language: string; label: string; note?: string }[];
  limits?: Record<string, number>;
  note?: string;
}

export const getLanguages = () => apiRequest<LanguageSupportPayload>("/system/languages");

/* -------------------------------------------------------------------- repos */

export interface ResolveResponse {
  repo: RepoMetadata;
  branches: { name: string; sha?: string | null; default?: boolean }[];
  canonical_url: string;
  github_rate_limit?: { remaining?: number; limit?: number; reset_at?: string | null } | null;
  already_imported?: string | null;
}

export const resolveRepo = (url: string) => apiRequest<ResolveResponse>("/repos/resolve", { method: "POST", body: { url } });
export const listRepos = (limit = 20) => apiRequest<{ repos: RepoSummary[] }>("/repos", { query: { limit } });
export const getRepo = (repoId: string, includeAnalyses = false) =>
  apiRequest<{ repo: RepoSummary; last_analysis: Analysis | null; analyses?: Analysis[] }>(`/repos/${repoId}`, {
    query: { include_analyses: includeAnalyses },
  });
export const deleteRepo = (repoId: string) => apiRequest<{ deleted: string }>(`/repos/${repoId}`, { method: "DELETE" });

/* ---------------------------------------------------------------- analyses */

export interface CreateAnalysisResponse {
  analysis_id: string;
  repo_id: string;
  status: string;
  reused: boolean;
  repo: RepoMetadata;
  branches: string[];
  analysis: Analysis;
}

export const createAnalysis = (url: string, branch?: string | null, force = true) =>
  apiRequest<CreateAnalysisResponse>("/analyses", { method: "POST", body: { url, branch: branch || null, force } });

export const listAnalyses = (limit = 20, repoId?: string) =>
  apiRequest<{ analyses: (Analysis & { repo?: { id: string; full_name?: string; url?: string } })[]; in_flight: string[] }>("/analyses", {
    query: { limit, repo_id: repoId },
  });

export const getAnalysis = (analysisId: string, includeOverview = false) =>
  apiRequest<{ analysis: Analysis; repo?: RepoMetadata; overview?: Overview }>(`/analyses/${analysisId}`, {
    query: { include_overview: includeOverview },
  });

export const cancelAnalysis = (analysisId: string) => apiRequest<{ analysis: Analysis }>(`/analyses/${analysisId}/cancel`, { method: "POST" });
export const deleteAnalysis = (analysisId: string) => apiRequest<{ deleted: string; next_analysis: Analysis | null }>(`/analyses/${analysisId}`, { method: "DELETE" });
export const getBundle = (analysisId: string) => apiRequest<Record<string, unknown>>(`/analyses/${analysisId}/bundle`);

/* ---------------------------------------------------------------- insights */

export const getOverview = (analysisId: string) => apiRequest<Overview>(`/analyses/${analysisId}/overview`);
export const getArchitecture = (analysisId: string) => apiRequest<ArchitectureGraph>(`/analyses/${analysisId}/architecture`);
export const getWorkflows = (analysisId: string, category?: string, limit = 60) =>
  apiRequest<WorkflowsPayload>(`/analyses/${analysisId}/workflows`, { query: { category, limit } });
export const getWorkflow = (analysisId: string, workflowId: string) =>
  apiRequest<{ workflow: Workflow }>(`/analyses/${analysisId}/workflows/${workflowId}`);
export const getDependencies = (analysisId: string, view: "files" | "modules" = "files", limit = 220) =>
  apiRequest<DependenciesPayload>(`/analyses/${analysisId}/dependencies`, { query: { view, limit } });
export const getApis = (analysisId: string) =>
  apiRequest<EndpointPayload>(`/analyses/${analysisId}/apis`);
export const getDatabase = (analysisId: string) => apiRequest<DatabasePayload>(`/analyses/${analysisId}/database`);
export const getQuality = (analysisId: string) => apiRequest<QualityPayload>(`/analyses/${analysisId}/quality`);
export const getFrameworks = (analysisId: string) => apiRequest<{ frameworks: FrameworkInfo[] }>(`/analyses/${analysisId}/frameworks`);
export const getInsights = (analysisId: string) => apiRequest<{ insights: Insight[]; note: string }>(`/analyses/${analysisId}/insights`);

/* ------------------------------------------------------------ code explorer */

export const getFileTree = (analysisId: string) => apiRequest<{ root: FileNode; total: number }>(`/analyses/${analysisId}/files`);
export const getFile = (analysisId: string, path: string) => apiRequest<FilePayload>(`/analyses/${analysisId}/file`, { query: { path } });
export const getSymbols = (analysisId: string, q?: string, limit = 50) =>
  apiRequest<{ symbols: SymbolInfo[]; stats: Record<string, number>; query?: string }>(`/analyses/${analysisId}/symbols`, { query: { q, limit } });
export interface SymbolReference {
  path: string;
  symbol: string;
  kind: string;
  line: number;
  via: string;
  caller_signature?: string | null;
}

export const getSymbolReferences = (analysisId: string, name: string, limit = 60) =>
  apiRequest<{ name: string; references: SymbolReference[] }>(
    `/analyses/${analysisId}/symbols/${encodeURIComponent(name)}/references`,
    { query: { limit } },
  );
export const search = (analysisId: string, query: string, limit = 12) =>
  apiRequest<{ query: string; hits: SearchHit[]; backend: string; embedding: { provider: string; neural: boolean } }>(
    `/analyses/${analysisId}/search`,
    { method: "POST", body: { query, limit } },
  );
export const grep = (analysisId: string, q: string, limit = 60) =>
  apiRequest<{ query: string; matches: { path: string; line: number; text: string; kind?: string }[] }>(`/analyses/${analysisId}/grep`, {
    query: { q, limit },
  });

/* ------------------------------------------------------------------ impact */

export const getImpact = (analysisId: string, path: string, symbol?: string | null, depth = 3) =>
  apiRequest<ImpactReport>(`/analyses/${analysisId}/impact`, { method: "POST", body: { path, symbol: symbol || null, depth } });

/* -------------------------------------------------------------------- docs */

export const getDoc = (analysisId: string, kind: string) => apiRequest<DocumentPayload>(`/analyses/${analysisId}/docs/${kind}`);
export const generateDoc = (analysisId: string, kind: string, useLlm = true) =>
  apiRequest<DocumentPayload>(`/analyses/${analysisId}/docs`, { method: "POST", body: { kind, use_llm: useLlm } });

/* -------------------------------------------------------------------- chat */

export const askQuestion = (analysisId: string, question: string, history: { role: string; content: string }[] = [], focusPath?: string | null) =>
  apiRequest<ChatAnswer>(`/analyses/${analysisId}/chat`, { method: "POST", body: { question, history, focus_path: focusPath || null } });

export const getChatHistory = (analysisId: string, limit = 40) =>
  apiRequest<{ messages: { id: string; role: string; content: string; citations: ChatAnswer["citations"]; model?: string | null; created_at?: string | null }[] }>(
    `/analyses/${analysisId}/chat/history`,
    { query: { limit } },
  );

export const getChatSuggestions = (analysisId: string) =>
  apiRequest<{ suggestions: string[] }>(`/analyses/${analysisId}/chat/suggestions`);

export type { Endpoint, FileNode, Overview, Workflow };
