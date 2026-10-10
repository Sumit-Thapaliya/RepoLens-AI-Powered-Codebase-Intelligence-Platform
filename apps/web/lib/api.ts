import { getWindowId } from "./window";
import type {
  Analysis,
  Capabilities,
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

/* ------------------------------------------------------------ response cache
 * Data of a finished analysis never changes, so its GET responses are kept in memory for this
 * window. Switching pages then shows the data at once. The cache is emptied whenever the window
 * lets go of an analysis, and it lives only in this window's memory (nothing is written to disk).
 */
const RESPONSE_CACHE_MAX_ENTRIES = 100;
const RESPONSE_CACHE_MAX_BYTES = 32 * 1024 * 1024;
const RESPONSE_CACHE_MAX_ENTRY_BYTES = 8 * 1024 * 1024;
type ResponseCacheEntry = { value: unknown; size: number };
const responseCache = new Map<string, ResponseCacheEntry>();
const inFlight = new Map<string, Promise<unknown>>();
let responseCacheBytes = 0;
let cacheGeneration = 0;

export function clearResponseCache(): void {
  cacheGeneration += 1;
  responseCache.clear();
  responseCacheBytes = 0;
  inFlight.clear();
}

let sessionPromise: Promise<void> | null = null;

/** Bootstrap the server-issued HttpOnly session before making protected requests. */
async function ensureApiSession(): Promise<void> {
  if (typeof window === "undefined") return;
  if (!sessionPromise) {
    sessionPromise = fetch(`${API_BASE}/session`, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
    }).then(async (response) => {
      if (!response.ok) {
        throw new ApiError("Could not establish a RepoLens session.", {
          code: "session_error",
          status: response.status,
          hint: "Refresh the page and try again.",
        });
      }
      const result = (await response.json()) as { new_session?: boolean };
      if (result.new_session) clearResponseCache();
    }).catch((error) => {
      sessionPromise = null;
      throw error;
    });
  }
  await sessionPromise;
}

function cachedGet<T>(path: string, options: { query?: Record<string, string | number | boolean | undefined | null> } = {}): Promise<T> {
  const key = `${path}?${JSON.stringify(options.query ?? {})}`;
  const cached = responseCache.get(key);
  if (cached) {
    responseCache.delete(key);
    responseCache.set(key, cached);
    return Promise.resolve(cached.value as T);
  }
  const pending = inFlight.get(key);
  if (pending) return pending as Promise<T>;

  const generation = cacheGeneration;
  const request = apiRequest<T>(path, options).then(
    (value) => {
      if (generation === cacheGeneration) {
        inFlight.delete(key);
        const serialized = JSON.stringify(value);
        const size = serialized ? serialized.length * 2 : 0;
        if (size <= RESPONSE_CACHE_MAX_ENTRY_BYTES) {
          responseCache.set(key, { value, size });
          responseCacheBytes += size;
          while (responseCache.size > RESPONSE_CACHE_MAX_ENTRIES || responseCacheBytes > RESPONSE_CACHE_MAX_BYTES) {
            const oldest = responseCache.keys().next().value;
            if (oldest === undefined) break;
            const removed = responseCache.get(oldest);
            responseCache.delete(oldest);
            responseCacheBytes -= removed?.size ?? 0;
          }
        }
      }
      return value;
    },
    (error) => {
      if (generation === cacheGeneration) inFlight.delete(key);
      throw error;
    },
  );
  inFlight.set(key, request);
  return request;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  await ensureApiSession();
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

  const send = () => fetch(url, {
    ...rest,
    headers: {
      "X-Window-Id": getWindowId(),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(headers || {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "include",
    cache: "no-store",
  });

  let response: Response;
  try {
    response = await send();
    if (response.status === 401 && typeof window !== "undefined") {
      // The API may have restarted in RAM-only mode. Establish a fresh session and
      // retry once; the old analysis will then receive a normal ownership/expiry 404.
      sessionPromise = null;
      await ensureApiSession();
      response = await send();
    }
  } catch (cause) {
    if (cause instanceof ApiError) throw cause;
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

export const createAnalysis = (url: string, branch?: string | null, force = true, windowId?: string) =>
  apiRequest<CreateAnalysisResponse>("/analyses", {
    method: "POST",
    body: { url, branch: branch || null, force, window_id: windowId ?? null },
  });

/** Only the runs listed in `ids` are returned - the runs this window owns. */
export const listAnalyses = (ids: string[], limit = 20) =>
  apiRequest<{ analyses: (Analysis & { repo?: { id: string; full_name?: string; url?: string } })[]; in_flight: string[] }>("/analyses", {
    query: { ids: ids.join(","), limit },
  });

/** Tells the server this window is still open. A 404 means the run was already discarded. */
export const heartbeatAnalysis = (analysisId: string, windowId: string) =>
  apiRequest<{ alive: boolean }>(`/analyses/${analysisId}/heartbeat`, { method: "POST", body: { window_id: windowId } });

/** This window lets go of a run. It is discarded at once if no other open window still owns it. */
export const releaseAnalysis = (analysisId: string, windowId: string) =>
  apiRequest<{ released: string; discarded: boolean }>(`/analyses/${analysisId}/release`, {
    method: "POST",
    body: { window_id: windowId },
  });

export const getAnalysis = (analysisId: string, includeOverview = false) =>
  apiRequest<{ analysis: Analysis; repo?: RepoMetadata; overview?: Overview }>(`/analyses/${analysisId}`, {
    query: { include_overview: includeOverview },
  });

export const cancelAnalysis = (analysisId: string) => apiRequest<{ analysis: Analysis }>(`/analyses/${analysisId}/cancel`, { method: "POST" });
export const deleteAnalysis = (analysisId: string) =>
  apiRequest<{ deleted: string; pending: boolean }>(`/analyses/${analysisId}`, { method: "DELETE" });
export const getBundle = (analysisId: string) => cachedGet<Record<string, unknown>>(`/analyses/${analysisId}/bundle`);

/* ---------------------------------------------------------------- insights */

export const getOverview = (analysisId: string) => cachedGet<Overview>(`/analyses/${analysisId}/overview`);
export const getArchitecture = (analysisId: string) => cachedGet<ArchitectureGraph>(`/analyses/${analysisId}/architecture`);
export const getWorkflows = (analysisId: string, category?: string, limit = 60) =>
  cachedGet<WorkflowsPayload>(`/analyses/${analysisId}/workflows`, { query: { category, limit } });
export const getWorkflow = (analysisId: string, workflowId: string) =>
  cachedGet<{ workflow: Workflow }>(`/analyses/${analysisId}/workflows/${workflowId}`);
export const getDependencies = (analysisId: string, view: "files" | "modules" = "files", limit = 220) =>
  cachedGet<DependenciesPayload>(`/analyses/${analysisId}/dependencies`, { query: { view, limit } });
export const getApis = (analysisId: string) =>
  cachedGet<EndpointPayload>(`/analyses/${analysisId}/apis`);
export const getDatabase = (analysisId: string) => cachedGet<DatabasePayload>(`/analyses/${analysisId}/database`);
export const getQuality = (analysisId: string) => cachedGet<QualityPayload>(`/analyses/${analysisId}/quality`);
export const getFrameworks = (analysisId: string) => cachedGet<{ frameworks: FrameworkInfo[] }>(`/analyses/${analysisId}/frameworks`);
export const getInsights = (analysisId: string) => cachedGet<{ insights: Insight[]; note: string }>(`/analyses/${analysisId}/insights`);

/* ------------------------------------------------------------ code explorer */

export const getFileTree = (analysisId: string) => cachedGet<{ root: FileNode; total: number }>(`/analyses/${analysisId}/files`);
export const getFile = (analysisId: string, path: string) => cachedGet<FilePayload>(`/analyses/${analysisId}/file`, { query: { path } });
export const getSymbols = (analysisId: string, q?: string, limit = 50) =>
  cachedGet<{ symbols: SymbolInfo[]; stats: Record<string, number>; query?: string }>(`/analyses/${analysisId}/symbols`, { query: { q, limit } });
export interface SymbolReference {
  path: string;
  symbol: string;
  kind: string;
  line: number;
  via: string;
  caller_signature?: string | null;
}

export const getSymbolReferences = (analysisId: string, name: string, limit = 60) =>
  cachedGet<{ name: string; references: SymbolReference[] }>(
    `/analyses/${analysisId}/symbols/${encodeURIComponent(name)}/references`,
    { query: { limit } },
  );
export const search = (analysisId: string, query: string, limit = 12) =>
  apiRequest<{ query: string; hits: SearchHit[]; ranking: string }>(
    `/analyses/${analysisId}/search`,
    { method: "POST", body: { query, limit } },
  );
export const grep = (analysisId: string, q: string, limit = 60) =>
  cachedGet<{ query: string; matches: { path: string; line: number; text: string; kind?: string }[] }>(`/analyses/${analysisId}/grep`, {
    query: { q, limit },
  });

/* ------------------------------------------------------------------ impact */

export const getImpact = (analysisId: string, path: string, symbol?: string | null, depth = 3) =>
  apiRequest<ImpactReport>(`/analyses/${analysisId}/impact`, { method: "POST", body: { path, symbol: symbol || null, depth } });

/* -------------------------------------------------------------------- docs */

export const getDoc = (analysisId: string, kind: string) => cachedGet<DocumentPayload>(`/analyses/${analysisId}/docs/${kind}`);
export const generateDoc = (analysisId: string, kind: string) =>
  apiRequest<DocumentPayload>(`/analyses/${analysisId}/docs`, { method: "POST", body: { kind } });

/** Loads the data the main pages need, so switching pages shows results at once. */
export function prefetchAnalysis(analysisId: string): void {
  const jobs: (() => Promise<unknown>)[] = [
    () => getOverview(analysisId),
    () => getArchitecture(analysisId),
    () => getDependencies(analysisId, "files", 220),
    () => getWorkflows(analysisId, undefined, 80),
    () => getApis(analysisId),
    () => getQuality(analysisId),
    () => getDatabase(analysisId),
    () => getFileTree(analysisId),
    () => getFrameworks(analysisId),
  ];
  void (async () => {
    for (const job of jobs) {
      try {
        await job();
      } catch {
        // A failed prefetch is harmless: the page loads the data itself when it opens.
      }
    }
  })();
}

export type { Endpoint, FileNode, Overview, Workflow };
