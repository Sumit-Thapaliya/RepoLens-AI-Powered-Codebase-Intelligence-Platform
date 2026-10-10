/**
 * Mirrors the JSON returned by the RepoLens API
 * (see packages/shared/repolens_shared/schemas.py - keep both in sync).
 */

export type AnalysisStatus = "queued" | "running" | "complete" | "failed" | "cancelled";

export interface StageProgress {
  id: string;
  label: string;
  status: "pending" | "running" | "done" | "skipped" | "failed";
  detail?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  elapsed_ms?: number | null;
}

export interface AnalysisError {
  code: string;
  message: string;
  hint?: string | null;
  detail?: unknown;
  reset_at?: string | null;
}

export interface Analysis {
  id: string;
  repo_id: string;
  status: AnalysisStatus;
  stage: string;
  progress: number;
  message?: string | null;
  error?: AnalysisError | null;
  warnings: { code: string; message: string; detail?: unknown }[];
  stages: StageProgress[];
  branch?: string | null;
  commit_sha?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  file_count: number;
  parsed_count: number;
  failed_count: number;
  skipped_count: number;
  provider_info: Record<string, unknown>;
}

export interface RepoMetadata {
  owner: string;
  name: string;
  full_name: string;
  url: string;
  description?: string | null;
  default_branch: string;
  html_url: string;
  stars: number;
  forks: number;
  watchers: number;
  open_issues: number;
  primary_language?: string | null;
  license?: string | null;
  topics: string[];
  size_kb: number;
  archived: boolean;
  is_fork: boolean;
  homepage?: string | null;
  created_at?: string | null;
  pushed_at?: string | null;
  updated_at?: string | null;
}

export interface LanguageStat {
  language: string;
  label: string;
  files: number;
  loc: number;
  percent: number;
}

export interface DatabaseTechnology {
  name: string;
  kind: string;
  confidence: number;
  evidence: string[];
}

export interface FrameworkInfo {
  name: string;
  ecosystem?: string | null;
  confidence: number;
  evidence: string[];
}

export interface Insight {
  id: string;
  kind: string;
  severity: "info" | "positive" | "warning" | "critical";
  title: string;
  detail: string;
  evidence: { path?: string | null; line?: number | null; label?: string }[];
  actions: { label: string; target: string }[];
}

export interface LayerInfo {
  id: string;
  label: string;
  description: string;
  files: number;
  loc: number;
  symbols: number;
  fan_in: number;
  fan_out: number;
  internal_edges: number;
  sample_files: { path: string; loc: number; symbols: number; fan_in: number; fan_out: number }[];
}

export interface ArchitectureGraph {
  layers: LayerInfo[];
  edges: {
    source: string;
    target: string;
    weight: number;
    kinds: string[];
    samples: { source: string; target: string; kind: string; line?: number | null }[];
  }[];
  entrypoints: { path: string; layer: string; kind: string; detail: string }[];
  notes: string[];
}

export interface Overview {
  repo: RepoMetadata;
  run: Analysis;
  files: number;
  parsed_files: number;
  failed_files: number;
  skipped_files: number;
  loc: number;
  languages: LanguageStat[];
  frameworks: FrameworkInfo[];
  databases: DatabaseTechnology[];
  functions: number;
  classes: number;
  symbols: number;
  endpoints: number;
  modules: number;
  edges: number;
  circular_dependencies: number;
  high_coupling_modules: number;
  workflows: number;
  test_files: number;
  ci_workflows: string[];
  commit_sha?: string | null;
  hubs: GraphNode[];
  layers: LayerInfo[];
  endpoint_stats: {
    total: number;
    methods: Record<string, number>;
    frameworks: Record<string, number>;
    authenticated: number;
    from_examples?: number;
    from_tests?: number;
    declared_in_multiple_places?: number;
  };
  database_stats: Record<string, number>;
  quality: { issues: number; by_severity: Record<string, number>; by_kind: Record<string, number>; health_score: number; health_label: string };
  graph_stats: Record<string, unknown> & {
    layers?: Record<string, number>;
    excluded_files?: number;
    graph_note?: string;
  };
  manifests: { path: string; ecosystem?: string; name?: string; version?: string; dependencies: number; scripts: string[]; error?: string | null }[];
  top_dependencies: { name: string; imports: number }[];
  parse_failures: { path: string; error: string }[];
  resolve_stats: Record<string, number>;
  warnings: { code: string; message: string }[];
  insights: Insight[];
  limits: Record<string, number>;
}

export interface Endpoint {
  id: string;
  method: string;
  path: string;
  handler?: string | null;
  file_path: string;
  line?: number | null;
  framework?: string | null;
  controller?: string | null;
  service?: string | null;
  auth_required?: boolean | null;
  evidence: string[];
  notes?: string | null;
  request_model?: string | null;
  response_model?: string | null;
  /** True when the primary declaration lives in an examples/ folder. */
  is_example?: boolean;
  /** True when the primary declaration lives in a test app. */
  is_test?: boolean;
  /** Every declaration of this (method, path) pair, primary first. */
  declarations?: EndpointDeclaration[];
}

export interface EndpointDeclaration {
  path: string;
  line?: number | null;
  framework?: string | null;
  handler?: string | null;
  is_example?: boolean;
  is_test?: boolean;
}

export interface EndpointPayload {
  endpoints: Endpoint[];
  frameworks: { framework: string; count: number }[];
  stats: {
    total: number;
    authenticated: number;
    unique_paths: number;
    from_examples?: number;
    from_tests?: number;
    declared_in_multiple_places?: number;
  };
}

export interface WorkflowStep {
  id: string;
  label: string;
  kind: string;
  file_path?: string | null;
  line?: number | null;
  symbol?: string | null;
  detail?: string | null;
  evidence?: string | null;
}

export interface Workflow {
  id: string;
  name: string;
  category: string;
  category_label?: string | null;
  description?: string | null;
  entry_point?: string | null;
  trigger?: string | null;
  framework?: string | null;
  steps: WorkflowStep[];
  confidence: number;
  evidence: string[];
  files: string[];
  trace_truncated: boolean;
  route?: { method?: string; path?: string; auth_required?: boolean } | null;
  /** application | example | test - where the traced entry point lives. */
  scope?: string | null;
  scope_note?: string | null;
}

export interface WorkflowsPayload {
  workflows: Workflow[];
  categories: { category: string; label: string; count: number }[];
  total: number;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  layer: string;
  path?: string | null;
  language?: string | null;
  loc?: number;
  symbols?: number;
  files?: number;
  fan_in?: number;
  fan_out?: number;
  coupling?: number;
  is_cycle_member?: boolean;
  is_test?: boolean;
  is_entrypoint?: boolean;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  weight: number;
  symbols: string[];
  line?: number | null;
}

export interface DependenciesPayload {
  view: "files" | "modules";
  nodes: GraphNode[];
  edges: GraphEdge[];
  cycles: { id: string; paths: string[]; size: number }[];
  hubs: (GraphNode & { is_cycle_member?: boolean })[];
  orphans?: string[];
  module_stats?: { module: string; files: number; loc: number; fan_in: number; fan_out: number }[];
  external_dependencies?: { name: string; imports: number }[];
  stats: Record<string, number | boolean | undefined> & { shown_nodes?: number; total_nodes?: number; truncated?: boolean };
  note?: string | null;
}

export interface DbField {
  name: string;
  line?: number | null;
  type?: string | null;
  on_delete?: string | null;
  primary_key?: boolean;
  foreign_key?: string | null;
  nullable?: boolean;
  unique?: boolean;
  default?: string | null;
  orm?: string;
}

export interface DbModel {
  id: string;
  name: string;
  table?: string | null;
  orm?: string | null;
  file_path: string;
  line?: number | null;
  fields: DbField[];
  relationships: { kind: string; name?: string; field?: string; target?: string; target_field?: string }[];
  source: string;
  line_hint?: number | null;
  query_count?: number;
  notes?: string;
}

export interface DbQuery {
  id: string;
  file_path: string;
  line?: number | null;
  kind: string;
  table?: string | null;
  orm?: string | null;
  snippet?: string | null;
}

export interface DatabasePayload {
  technologies: DatabaseTechnology[];
  models: DbModel[];
  queries: DbQuery[];
  migrations: { id: string; path: string; tables: string[]; framework?: string | null; operations: number }[];
  relations: { source: string; source_table?: string | null; target: string; target_table?: string | null; kind: string; field?: string | null; resolved: boolean }[];
  orms: string[];
  notes: string[];
  stats: Record<string, number | Record<string, number>>;
}

export interface QualityIssue {
  id: string;
  kind: string;
  severity: "info" | "low" | "medium" | "high";
  title: string;
  detail: string;
  files: string[];
  symbol?: string | null;
  metric: Record<string, unknown>;
  heuristic: boolean;
}

export interface QualityPayload {
  issues: QualityIssue[];
  summary: { issues: number; by_severity: Record<string, number>; by_kind: Record<string, number>; health_score: number; health_label: string };
  metrics: Record<string, number | Record<string, number>>;
  disclaimer: string;
}

export interface SymbolInfo {
  id: string;
  path: string;
  name: string;
  kind: string;
  start_line: number;
  end_line: number;
  signature?: string | null;
  params: string[];
  decorators: string[];
  bases: string[];
  docstring?: string | null;
  complexity: number;
  loc: number;
  parent?: string | null;
  exported: boolean;
  is_async: boolean;
  calls: { name: string; line: number; qualifier?: string | null; full: string }[];
}

export interface FileNode {
  name: string;
  count?: number;
  path: string;
  type: "file" | "dir";
  children?: FileNode[];
  language?: string;
  loc?: number;
  layer?: string;
  test?: boolean;
  symbols?: number;
  parsed?: boolean;
  parse_error?: string | null;
}

export interface FilePayload {
  path: string;
  language: string;
  content: string;
  truncated: boolean;
  size_bytes: number;
  loc: number;
  layer: string;
  parsed: boolean;
  parse_error?: string | null;
  warnings: string[];
  symbols: SymbolInfo[];
  imports: { path: string; kind: string; symbols: string[]; line?: number | null }[];
  dependents: { path: string; kind: string; symbols: string[]; line?: number | null }[];
  artifact_note?: string;
}

export interface SearchHit {
  id: string;
  path: string;
  symbol?: string | null;
  kind: string;
  start_line: number;
  end_line: number;
  score: number;
  snippet: string;
}

export interface ImpactFile {
  path: string;
  layer?: string;
  loc?: number;
  symbols?: number;
  files?: number;
  fan_in?: number;
  fan_out?: number;
  coupling?: number;
  kind?: string;
  is_test?: boolean;
}

export interface ImpactReport {
  target: { path: string; symbol?: string | null; layer?: string; loc?: number; symbol_info?: SymbolInfo | null };
  direct_dependencies: ImpactFile[];
  indirect_dependencies: (ImpactFile & { distance: number; via: string })[];
  dependents: ImpactFile[];
  indirect_dependents: (ImpactFile & { distance: number; via: string })[];
  affected_endpoints: Endpoint[];
  affected_workflows: { id: string; name: string; trigger?: string | null; category: string; confidence: number; impacted_steps: { label: string; file_path?: string | null; kind: string }[]; distance: number }[];
  related_tests: (ImpactFile & { reason: string })[];
  risks: { level: "low" | "medium" | "high"; title: string; detail: string; heuristic: boolean }[];
  graph?: { nodes: GraphNode[]; edges: GraphEdge[] };
  notes: string[];
  error?: string;
}

export interface Capabilities {
  storage: { mode: "memory" | "postgres"; dialect: string; local_files: boolean; note: string; max_stored_runs: number };
  search: { ranking: string; note: string };
  github: { authenticated: boolean; rate_limit: string; note: string };
  limits: Record<string, number>;
}

export interface RepoSummary {
  id: string;
  full_name: string;
  url: string;
  description?: string | null;
  default_branch: string;
  stars: number;
  primary_language?: string | null;
  updated_at?: string | null;
  last_analysis?: Analysis | null;
}

export interface DocumentPayload {
  kind: string;
  title: string;
  markdown: string;
  generated_by: string;
}
