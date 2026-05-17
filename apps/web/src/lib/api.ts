/**
 * Typed API client — thin fetch wrapper around the lex-agents backend.
 * Server-side calls use API_BASE_URL; browser calls use NEXT_PUBLIC_API_URL.
 */

// Server-side: use API_BASE_URL (runtime env var set in ECS task definition).
// Browser-side: use "" (relative path) — Next.js rewrites in next.config.mjs
// proxy /health, /version, /auth/*, /api/v1/* to the backend server-side,
// so the browser never needs to know the API URL and no URL is baked at build time.
const API_BASE =
  typeof window === "undefined"
    ? (process.env["API_BASE_URL"] ?? "http://localhost:8000")
    : "";

// ---------------------------------------------------------------------------
// Error types
// ---------------------------------------------------------------------------

/** User-facing error with a Spanish message and a machine-readable code. */
export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function _statusMessage(status: number, detail?: string): string {
  // Special-case SYSTEM_KILLED before generic 503
  if (status === 503 && detail?.includes("SYSTEM_KILLED")) {
    return "El sistema está temporalmente desactivado por un administrador. Contacta con el equipo de operaciones.";
  }
  switch (status) {
    case 400:
      return "La petición no es válida. Revisa los datos introducidos.";
    case 401:
      return "Tu sesión ha caducado. Recarga la página para volver a autenticarte.";
    case 403:
      return "No tienes permiso para realizar esta acción.";
    case 404:
      return "El recurso solicitado no existe o aún no está disponible.";
    case 413:
      return "El contenido enviado es demasiado grande (límite: 64 KB).";
    case 422:
      return detail
        ? `Datos no válidos: ${detail}`
        : "Los datos enviados no son correctos. Revisa el formulario.";
    case 429:
      return "Demasiadas peticiones seguidas. Espera un momento e inténtalo de nuevo.";
    case 500:
      return "Error interno del servidor. El equipo técnico ha sido notificado.";
    case 503:
      return "El servicio no está disponible en este momento. Inténtalo de nuevo en unos segundos.";
    default:
      return `Error del servidor (${status}). Inténtalo de nuevo o contacta con soporte.`;
  }
}

async function _parseErrorDetail(res: Response): Promise<string | undefined> {
  try {
    const body = (await res.clone().json()) as {
      detail?: string | { code?: string; message?: string };
    };
    if (typeof body.detail === "string") return body.detail;
    if (typeof body.detail === "object" && body.detail !== null) {
      return body.detail.message ?? body.detail.code;
    }
  } catch {
    // not JSON
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Types (mirroring FastAPI response models)
// ---------------------------------------------------------------------------

export type DepsStatus = {
  qdrant: "healthy" | "degraded" | "unavailable";
  anthropic_api: "configured" | "not_configured";
};

export type HealthResponse = {
  status: "healthy" | "degraded" | "unavailable";
  version: string;
  deps_status: DepsStatus;
};

export type VersionResponse = {
  version: string;
  commit_sha: string;
  build_time: string;
  python_version: string;
};

// ---------------------------------------------------------------------------
// Token management (browser only)
// ---------------------------------------------------------------------------

const TOKEN_KEY = "lex_agents_token";

function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(TOKEN_KEY);
}

function setStoredToken(token: string): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(TOKEN_KEY, token);
}

async function fetchToken(): Promise<string | null> {
  try {
    const body = new URLSearchParams({
      username: "demo",
      password: "demo1234",
    });
    const res = await fetch(`${API_BASE}/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { access_token: string };
    setStoredToken(data.access_token);
    return data.access_token;
  } catch {
    return null;
  }
}

async function getToken(): Promise<string | null> {
  const stored = getStoredToken();
  if (stored) return stored;
  return fetchToken();
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const isPublicEndpoint =
    path.startsWith("/health") || path.startsWith("/version");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };

  if (!isPublicEndpoint && typeof window !== "undefined") {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(
      "NETWORK_ERROR",
      "No se puede conectar con el servidor. Asegúrate de que los servicios están activos (`make dev`).",
    );
  }

  if (res.status === 401 && typeof window !== "undefined") {
    // Token expired — re-fetch and retry once
    const newToken = await fetchToken();
    if (newToken) {
      headers["Authorization"] = `Bearer ${newToken}`;
      let retry: Response;
      try {
        retry = await fetch(`${API_BASE}${path}`, { ...init, headers });
      } catch {
        throw new ApiError(
          "NETWORK_ERROR",
          "No se puede conectar con el servidor. Asegúrate de que los servicios están activos (`make dev`).",
        );
      }
      if (!retry.ok) {
        const detail = await _parseErrorDetail(retry);
        throw new ApiError(
          `HTTP_${retry.status}`,
          _statusMessage(retry.status, detail),
          retry.status,
        );
      }
      if (retry.status === 204) return undefined as T;
      return retry.json() as Promise<T>;
    }
  }

  if (!res.ok) {
    const detail = await _parseErrorDetail(res);
    throw new ApiError(
      `HTTP_${res.status}`,
      _statusMessage(res.status, detail),
      res.status,
    );
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}

export async function getVersion(): Promise<VersionResponse> {
  return apiFetch<VersionResponse>("/version");
}

// ---------------------------------------------------------------------------
// Consult types
// ---------------------------------------------------------------------------

export type CitationMapping = {
  index: number;
  chunk_id: string;
  source_id: string;
  hierarchy_path: string;
  fragment_text: string;
  fragment_offset?: number;
};

export type VerificationReport = {
  response_id: string;
  claims_total: number;
  claims_passed: number;
  claims_failed: number;
  claims_uncertain: number;
  llm_calls_made: number;
  uncited_claims: string[];
  broken_refs: number[];
  status: "green" | "amber" | "red";
};

// ---------------------------------------------------------------------------
// Comparative law types (ADR 0027)
// ---------------------------------------------------------------------------

export type CoverageLevel = "full" | "partial" | "insufficient";
export type RiskLevel = "low" | "medium" | "high";

export type JurisdictionEntry = {
  text: string | null;
  refs: number[];
  coverage: CoverageLevel;
  note: string | null;
};

export type ComparativeDimension = {
  name: string;
  by_jurisdiction: Record<string, JurisdictionEntry>;
};

export type Divergence = {
  dimension: string;
  description: string;
  jurisdictions_involved: string[];
  severity: RiskLevel;
};

export type CoverageGap = {
  jurisdiction: string;
  reason: string;
  recommendation: string;
};

export type ComparativeResponse = {
  trace_id: string;
  issue: string;
  jurisdictions_compared: string[];
  dimensions: ComparativeDimension[];
  divergences: Divergence[];
  common_ground: string[];
  risk_differential: Record<string, RiskLevel>;
  risk_rationale: string;
  coverage_gaps: CoverageGap[];
  citations: CitationMapping[];
  verification_status: "green" | "amber" | "red";
  synthesised_at: string;
};

export type ConsultResponse = {
  trace_id: string;
  answer: string;
  citations: CitationMapping[];
  verification: VerificationReport | null;
  query_rewritten: string;
  routing: {
    branch: string;
    jurisdictions?: string[];
    output_type?: string;
    depth?: string;
  };
  metadata: Record<string, unknown>;
  // PMJ metadata (present when depth=standard or deep)
  depth_used?: string;
  iterations?: number;
  planner_output?: {
    branches: { name: string; priority: number; weight: number }[];
    jurisdictions: string[];
    output_type: string;
    depth: string;
    sub_tasks: { id: string; branch: string; weight: number }[];
  } | null;
  judge_verdict?: {
    verdict: "publish" | "revise" | "reject";
    scores: Record<string, number>;
    gaps: string[];
    iteration_brief: string;
    iteration: number;
  } | null;
  cost_breakdown_by_agent?: Record<string, number>;
  branch_answers?: Record<string, string>;
  comparative_output?: ComparativeResponse | null;
};

export type ConsultationSummary = {
  trace_id: string;
  created_at: string;
  query: string;
  latency_ms: number | null;
  verification_status: string;
  depth_used: string | null;
  branch: string | null;
};

export type ConsultationFilter = {
  q?: string;
  depth?: string;
  branch?: string;
  status?: string;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
};

// ---------------------------------------------------------------------------
// Consult API functions
// ---------------------------------------------------------------------------

export async function consultQuery(
  query: string,
  outputType?: string,
  jurisdictionHint?: string,
  depth?: "shallow" | "standard" | "deep",
  jurisdictions?: string[],
): Promise<ConsultResponse> {
  return apiFetch<ConsultResponse>("/api/v1/consult", {
    method: "POST",
    body: JSON.stringify({
      query,
      output_type: outputType ?? null,
      jurisdiction_hint: jurisdictionHint ?? null,
      depth: depth ?? null,
      jurisdictions:
        jurisdictions && jurisdictions.length > 0 ? jurisdictions : null,
    }),
  });
}

// ---------------------------------------------------------------------------
// Streaming consult
// ---------------------------------------------------------------------------

export type StreamHandlers = {
  onProgress: (step: string, message: string, pct: number) => void;
  onToken: (delta: string) => void;
  onResult: (response: ConsultResponse) => void;
  onError: (message: string) => void;
  onDone: () => void;
};

/**
 * POST /api/v1/consult/stream — SSE streaming variant.
 * Uses fetch + ReadableStream (not EventSource, which only supports GET).
 * Returns a cleanup function that aborts the stream.
 */
export function consultQueryStream(
  query: string,
  handlers: StreamHandlers,
  options?: {
    outputType?: string;
    jurisdictionHint?: string;
    depth?: "shallow" | "standard" | "deep";
    jurisdictions?: string[];
  },
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const token =
        typeof window !== "undefined"
          ? localStorage.getItem("auth_token")
          : null;

      const res = await fetch(`${API_BASE}/api/v1/consult/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          query,
          output_type: options?.outputType ?? null,
          jurisdiction_hint: options?.jurisdictionHint ?? null,
          depth: options?.depth ?? null,
          jurisdictions:
            options?.jurisdictions && options.jurisdictions.length > 0
              ? options.jurisdictions
              : null,
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const text = await res.text().catch(() => "");
        handlers.onError(`Error ${res.status}: ${text || res.statusText}`);
        return;
      }

      if (!res.body) {
        handlers.onError("No response body");
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Process complete SSE messages (delimited by \n\n)
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          const lines = part.split("\n");
          let eventName = "message";
          let dataStr = "";

          for (const line of lines) {
            if (line.startsWith("event: ")) {
              eventName = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              dataStr = line.slice(6).trim();
            }
          }

          if (!dataStr) continue;
          let payload: Record<string, unknown>;
          try {
            payload = JSON.parse(dataStr);
          } catch {
            continue;
          }

          if (eventName === "progress") {
            handlers.onProgress(
              String(payload["step"] ?? ""),
              String(payload["message"] ?? ""),
              Number(payload["pct"] ?? 0),
            );
          } else if (eventName === "token") {
            handlers.onToken(String(payload["delta"] ?? ""));
          } else if (eventName === "result") {
            handlers.onResult(payload as unknown as ConsultResponse);
          } else if (eventName === "done") {
            handlers.onDone();
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      handlers.onError((err as Error).message ?? "Error desconocido");
    }
  })();

  return () => controller.abort();
}

export async function getConsultation(
  traceId: string,
): Promise<ConsultResponse> {
  return apiFetch<ConsultResponse>(`/api/v1/consult/${traceId}`);
}

export async function listConsultations(
  filters: ConsultationFilter = {},
): Promise<ConsultationSummary[]> {
  const params = new URLSearchParams();
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined)
    params.set("offset", String(filters.offset));
  if (filters.q) params.set("q", filters.q);
  if (filters.depth) params.set("depth", filters.depth);
  if (filters.branch) params.set("branch", filters.branch);
  if (filters.status) params.set("status", filters.status);
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (!params.has("limit")) params.set("limit", "50");
  const qs = params.toString();
  return apiFetch<ConsultationSummary[]>(`/api/v1/consult?${qs}`);
}

export function getComparativeExportUrl(traceId: string): string {
  return `${API_BASE}/api/v1/consult/${traceId}/export/comparative`;
}

// ---------------------------------------------------------------------------
// Feedback types
// ---------------------------------------------------------------------------

export type FeedbackVerdict = "aceptable" | "dudoso" | "incorrecto";

export type FeedbackRecord = {
  id: number;
  trace_id: string;
  verdict: FeedbackVerdict;
  notes: string | null;
  created_at: string;
};

// ---------------------------------------------------------------------------
// Audit types
// ---------------------------------------------------------------------------

export type AuditStatus = "pending" | "reviewing" | "reviewed";
export type AuditVerdict = "correcto" | "dudoso" | "incorrecto";

export type AuditSample = {
  id: number;
  trace_id: string;
  query: string;
  branch: string;
  depth: string;
  sampled_at: string;
  status: AuditStatus;
  reviewer: string | null;
  review_notes: string | null;
  review_verdict: AuditVerdict | null;
};

export async function listAuditSamples(
  status?: AuditStatus,
): Promise<AuditSample[]> {
  const qs = status ? `?status=${status}` : "";
  return apiFetch<AuditSample[]>(`/api/v1/audit${qs}`);
}

export async function getAuditSample(id: number): Promise<AuditSample> {
  return apiFetch<AuditSample>(`/api/v1/audit/${id}`);
}

export async function submitAuditReview(
  id: number,
  verdict: AuditVerdict,
  notes: string,
): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/api/v1/audit/${id}/review`, {
    method: "PUT",
    body: JSON.stringify({ verdict, notes }),
  });
}

// ---------------------------------------------------------------------------
// Document types
// ---------------------------------------------------------------------------

export type UploadResponse = {
  doc_id: string;
  filename: string;
  sha256: string;
  mime_type: string;
  segment_count: number;
  page_count: number | null;
  expires_at: string;
};

export type AnalysisResponse = {
  doc_id: string;
  trace_id: string;
  filename: string;
  mode: string;
  analysis_text: string;
  segment_count: number;
  verification_status: "green" | "amber" | "red";
  analysed_at: string;
};

export type CompareResponse = {
  doc_ids: string[];
  trace_id: string;
  diff_text: string;
  verification_status: "green" | "amber" | "red";
  analysed_at: string;
};

export type AnalysisMode =
  | "resumen_ejecutivo"
  | "analisis_clausulas"
  | "riesgos"
  | "comparativa";

// ---------------------------------------------------------------------------
// Document API functions
// ---------------------------------------------------------------------------

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const token =
    typeof window !== "undefined"
      ? (sessionStorage.getItem("lex_agents_token") ?? (await getToken()))
      : null;

  const formData = new FormData();
  formData.append("file", file);

  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}/api/v1/documents/upload`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json() as Promise<UploadResponse>;
}

export async function analyzeDocument(
  docId: string,
  query = "Analiza este documento.",
  mode: AnalysisMode = "riesgos",
): Promise<AnalysisResponse> {
  return apiFetch<AnalysisResponse>(`/api/v1/documents/${docId}/analyze`, {
    method: "POST",
    body: JSON.stringify({ query, mode }),
  });
}

export async function compareDocuments(
  docIds: [string, string],
  query = "Compara estos dos documentos.",
): Promise<CompareResponse> {
  return apiFetch<CompareResponse>("/api/v1/documents/compare", {
    method: "POST",
    body: JSON.stringify({ doc_ids: docIds, query }),
  });
}

export async function deleteDocument(docId: string): Promise<void> {
  const token =
    typeof window !== "undefined"
      ? (sessionStorage.getItem("lex_agents_token") ?? (await getToken()))
      : null;
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  await fetch(`${API_BASE}/api/v1/documents/${docId}`, {
    method: "DELETE",
    headers,
  });
}

// ─── Governance types & API ───────────────────────────────────────────────────

export type ProposalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "changes_requested";

export type PromptEvolutionProposal = {
  id: number;
  pr_number: number | null;
  pr_url: string;
  specialist: string;
  diff: string;
  motivating_cases: string | null;
  simulation_results: string | null;
  status: ProposalStatus;
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
  decision_reason: string | null;
};

export type SourceStatus = {
  source_id: string;
  display_name: string | null;
  status: "active" | "paused";
  paused_at: string | null;
  paused_by: string | null;
  paused_reason: string | null;
  last_synced_at: string | null;
};

export type RecentDecision = {
  id: number;
  timestamp: string;
  actor: string;
  actor_role: string;
  action_type: string;
  target_type: string;
  target_id: string | null;
  reason: string;
};

export type AuditEntry = {
  id: number;
  timestamp: string;
  actor_user_id: string;
  actor_role: string;
  action_type: string;
  target_type: string;
  target_id: string | null;
  before_state: string | null;
  after_state: string | null;
  reason: string;
  correlation_id: string | null;
  checksum_self: string | null;
};

export type AuditFilter = {
  actor?: string;
  action_type?: string;
  target_type?: string;
  since?: string;
  until?: string;
  limit?: number;
};

export type ChainVerification = {
  valid: boolean;
  total: number;
  broken_at: number | null;
};

// Governance endpoints
export const listProposals = (status?: string) =>
  apiFetch<PromptEvolutionProposal[]>(
    `/api/v1/admin/governance/proposals${status ? `?status=${status}` : ""}`,
  );

export const approveProposal = (prNumber: number, reason: string) =>
  apiFetch<{ status: string; pr_number: number; gh_merge_ok: boolean }>(
    `/api/v1/admin/governance/proposals/${prNumber}/approve`,
    { method: "POST", body: JSON.stringify({ reason }) },
  );

export const rejectProposal = (prNumber: number, reason: string) =>
  apiFetch<{ status: string; pr_number: number; gh_close_ok: boolean }>(
    `/api/v1/admin/governance/proposals/${prNumber}/reject`,
    { method: "POST", body: JSON.stringify({ reason }) },
  );

export const requestChangesProposal = (prNumber: number, comment: string) =>
  apiFetch<{ status: string; pr_number: number }>(
    `/api/v1/admin/governance/proposals/${prNumber}/request-changes`,
    { method: "POST", body: JSON.stringify({ comment }) },
  );

export const listSources = () =>
  apiFetch<SourceStatus[]>("/api/v1/admin/governance/sources");

export const pauseSource = (sourceId: string, reason: string) =>
  apiFetch<{ source_id: string; status: string }>(
    `/api/v1/admin/governance/sources/${sourceId}/pause`,
    { method: "POST", body: JSON.stringify({ reason }) },
  );

export const resumeSource = (sourceId: string, reason: string) =>
  apiFetch<{ source_id: string; status: string }>(
    `/api/v1/admin/governance/sources/${sourceId}/resume`,
    { method: "POST", body: JSON.stringify({ reason }) },
  );

export const listRecentDecisions = (limit = 50) =>
  apiFetch<RecentDecision[]>(
    `/api/v1/admin/governance/recent-decisions?limit=${limit}`,
  );

// Audit trail endpoints
export const listAuditTrail = (filters: AuditFilter = {}) => {
  const params = new URLSearchParams();
  if (filters.actor) params.set("actor", filters.actor);
  if (filters.action_type) params.set("action_type", filters.action_type);
  if (filters.target_type) params.set("target_type", filters.target_type);
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (filters.limit) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return apiFetch<AuditEntry[]>(
    `/api/v1/admin/audit-trail${qs ? `?${qs}` : ""}`,
  );
};

export const getAuditEntry = (id: number) =>
  apiFetch<AuditEntry>(`/api/v1/admin/audit-trail/${id}`);

export const verifyAuditChain = () =>
  apiFetch<ChainVerification>("/api/v1/admin/audit-trail/verify");

export const exportAuditTrail = async (
  format: "csv" | "json",
): Promise<Blob> => {
  const token =
    typeof window !== "undefined"
      ? (sessionStorage.getItem("lex_agents_token") ?? (await getToken()))
      : null;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}/api/v1/admin/audit-trail/export`, {
    method: "POST",
    headers,
    body: JSON.stringify({ format }),
  });
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  return res.blob();
};

// ─── System state (ADR-0032) ──────────────────────────────────────────────────

export type FlagRow = {
  key: string;
  value: string;
  updated_at: string;
  updated_by: string;
};

export type KillSwitchRow = {
  target: string;
  engaged: boolean;
  engaged_at: string | null;
  engaged_by: string | null;
  reason: string | null;
};

export type GlobalState = {
  flags: FlagRow[];
  kill_switches: KillSwitchRow[];
};

export const getSystemState = () =>
  apiFetch<GlobalState>("/api/v1/admin/system/state");

export const setFlag = (key: string, value: unknown, reason: string) =>
  apiFetch<void>(`/api/v1/admin/system/flags/${encodeURIComponent(key)}`, {
    method: "PUT",
    body: JSON.stringify({ value, reason }),
  });

export const setKillSwitch = (
  target: string,
  engage: boolean,
  reason: string,
) =>
  apiFetch<void>(`/api/v1/admin/system/kill/${encodeURIComponent(target)}`, {
    method: "PUT",
    body: JSON.stringify({ engage, reason }),
  });

// ─── Ops: agents ──────────────────────────────────────────────────────────────

export type AgentStatus = {
  name: string;
  status: string;
  current_prompt_version: string | null;
  model: string;
  kill_switch_engaged: boolean;
  invocations_last_24h: number;
  avg_latency_ms_last_24h: number | null;
  cost_usd_last_24h: number;
  last_error: string | null;
};

export const listAgents = () => apiFetch<AgentStatus[]>("/api/v1/admin/agents");

// ─── Ops: RAG & Memory ────────────────────────────────────────────────────────

export type CollectionInfo = {
  name: string;
  vectors_count: number;
  payload_schema_keys: string[];
};

export type RagStatus = {
  collections: CollectionInfo[];
  total_vectors: number;
};

export type MemoryStatus = {
  procedural_patterns_count: number;
  semantic_files_count: number;
};

export type ProceduralPatternRow = {
  filename: string;
  content: string;
};

export const getRagStatus = () =>
  apiFetch<RagStatus>("/api/v1/admin/rag/status");

export const getMemoryStatus = () =>
  apiFetch<MemoryStatus>("/api/v1/admin/memory/status");

export const listProceduralPatterns = () =>
  apiFetch<ProceduralPatternRow[]>("/api/v1/admin/memory/procedural");

export const getSemanticFile = (filename: string) =>
  apiFetch<{ filename: string; content: string }>(
    `/api/v1/admin/memory/semantic/${encodeURIComponent(filename)}`,
  );

export const forceResync = (source: string, reason: string) =>
  apiFetch<void>(
    `/api/v1/admin/sources/${encodeURIComponent(source)}/force-resync`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    },
  );

// ─── Notifications ─────────────────────────────────────────────────────────────

export type NotificationRow = {
  id: number;
  source: string;
  category: "critical" | "warning" | "info";
  title: string;
  body: string;
  payload: string | null;
  correlation_id: string | null;
  created_at: string;
  read_at: string | null;
  read_by: string | null;
};

export const getNotificationsCount = () =>
  apiFetch<{ unread: number }>("/api/v1/admin/notifications/count");

export const listNotifications = (unreadOnly = false) =>
  apiFetch<NotificationRow[]>(
    `/api/v1/admin/notifications${unreadOnly ? "?unread_only=true" : ""}`,
  );

export const markNotificationRead = (id: number) =>
  apiFetch<void>(`/api/v1/admin/notifications/${id}/read`, { method: "PUT" });

export const markAllNotificationsRead = () =>
  apiFetch<void>("/api/v1/admin/notifications/read-all", { method: "PUT" });

// ---------------------------------------------------------------------------
// Federation — AWS Console signin URLs
// ---------------------------------------------------------------------------

export type AwsService =
  | "cloudwatch"
  | "xray"
  | "step-functions"
  | "bedrock"
  | "agentcore";

export interface FederationUrlOptions {
  dashboard?: string;
  resourceId?: string;
}

export interface FederationUrlResponse {
  url: string;
  expires_in: number;
}

export const getFederationUrl = (
  service: AwsService,
  options?: FederationUrlOptions,
): Promise<FederationUrlResponse> =>
  apiFetch<FederationUrlResponse>("/api/v1/admin/federation/aws-console-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      service,
      dashboard: options?.dashboard,
      resource_id: options?.resourceId,
    }),
  });

// ---------------------------------------------------------------------------
// Platform status — health of self-hosted tools
// ---------------------------------------------------------------------------

export interface ToolStatus {
  name: string;
  url: string;
  pattern: "iframe" | "federated";
  healthy: boolean | null;
}

export async function getPlatformStatus(): Promise<ToolStatus[]> {
  const grafanaUrl = process.env.NEXT_PUBLIC_GRAFANA_URL ?? "";
  const langfuseUrl = process.env.NEXT_PUBLIC_LANGFUSE_URL ?? "";
  const jaegerUrl = process.env.NEXT_PUBLIC_JAEGER_URL ?? "";

  const probes: Array<{
    name: string;
    url: string;
    pattern: "iframe" | "federated";
  }> = [
    { name: "Grafana", url: grafanaUrl, pattern: "iframe" },
    { name: "Langfuse", url: langfuseUrl, pattern: "iframe" },
    { name: "Jaeger", url: jaegerUrl, pattern: "iframe" },
    { name: "CloudWatch", url: "", pattern: "federated" },
    { name: "X-Ray", url: "", pattern: "federated" },
    { name: "Step Functions", url: "", pattern: "federated" },
    { name: "Bedrock", url: "", pattern: "federated" },
    { name: "AgentCore", url: "", pattern: "federated" },
  ];

  const results = await Promise.all(
    probes.map(async ({ name, url, pattern }) => {
      if (pattern === "federated" || !url) {
        return { name, url, pattern, healthy: null };
      }
      try {
        const res = await fetch(`${url}/api/health`, {
          signal: AbortSignal.timeout(3000),
          mode: "no-cors",
        });
        return { name, url, pattern, healthy: res.type === "opaque" || res.ok };
      } catch {
        return { name, url, pattern, healthy: false };
      }
    }),
  );

  return results;
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export type UserRow = {
  username: string;
  role: string;
};

export const listUsers = () => apiFetch<UserRow[]>("/api/v1/admin/users");

export type CreateUserRequest = {
  username: string;
  password: string;
  role: string;
};
export type UpdateUserRequest = {
  role?: string;
  password?: string;
  disabled?: boolean;
};

export const createUser = (body: CreateUserRequest) =>
  apiFetch<UserRow>("/api/v1/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const updateUser = (username: string, body: UpdateUserRequest) =>
  apiFetch<UserRow>(`/api/v1/admin/users/${username}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const deleteUser = (username: string) =>
  apiFetch<void>(`/api/v1/admin/users/${username}`, { method: "DELETE" });

// ---------------------------------------------------------------------------
// Pipelines
// ---------------------------------------------------------------------------

export type PipelineExecution = {
  name: string;
  execution_arn: string;
  status: string;
  start_date: string | null;
  stop_date: string | null;
};

export type PipelinesResponse = {
  executions: PipelineExecution[];
  status: "ok" | "unavailable" | "not_configured";
  message?: string;
};

export const listPipelines = () =>
  apiFetch<PipelinesResponse>("/api/v1/admin/pipelines");

// ---------------------------------------------------------------------------
// Platform config
// ---------------------------------------------------------------------------

export type ServiceConfig = {
  name: string;
  configured: boolean;
  value_hint?: string;
};

export type PlatformConfig = {
  env: string;
  db_mode: string;
  auth_enabled: boolean;
  log_level: string;
  services: ServiceConfig[];
  jwt_algorithm: string;
  otel_service_name: string;
};

export const getPlatformConfig = () =>
  apiFetch<PlatformConfig>("/api/v1/admin/platform-config");

// ---------------------------------------------------------------------------
// Sessions (ADR 0057)
// ---------------------------------------------------------------------------

export type SessionRow = {
  id: string;
  username: string;
  role: string;
  ip_address: string;
  user_agent: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  revoked_at: string | null;
  suspicious: boolean;
};

export const getSessions = (username: string) =>
  apiFetch<SessionRow[]>(`/api/v1/admin/users/${username}/sessions`);

export const revokeSession = (sessionId: string) =>
  apiFetch<void>(`/api/v1/admin/sessions/${sessionId}`, { method: "DELETE" });

export const revokeAllSessions = (username: string) =>
  apiFetch<void>(`/api/v1/admin/users/${username}/sessions`, {
    method: "DELETE",
  });

export const getMySessions = () =>
  apiFetch<SessionRow[]>("/api/v1/me/sessions");

export const revokeOtherSessions = () =>
  apiFetch<void>("/api/v1/me/sessions/others", { method: "DELETE" });
