/**
 * Typed API client — thin fetch wrapper around the lex-agents backend.
 * Server-side calls use API_BASE_URL; browser calls use NEXT_PUBLIC_API_URL.
 */

const API_BASE =
  typeof window === "undefined"
    ? (process.env["API_BASE_URL"] ?? "http://localhost:8000")
    : (process.env["NEXT_PUBLIC_API_URL"] ?? "http://localhost:8000");

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
  const isAuthEndpoint =
    path.startsWith("/health") || path.startsWith("/version");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };

  if (!isAuthEndpoint && typeof window !== "undefined") {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (res.status === 401 && typeof window !== "undefined") {
    // Token expired — re-fetch and retry once
    const token = await fetchToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
      const retry = await fetch(`${API_BASE}${path}`, { ...init, headers });
      if (!retry.ok)
        throw new Error(`API error ${retry.status}: ${retry.statusText}`);
      return retry.json() as Promise<T>;
    }
  }

  if (!res.ok) throw new Error(`API error ${res.status}: ${res.statusText}`);
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

export async function getConsultation(
  traceId: string,
): Promise<ConsultResponse> {
  return apiFetch<ConsultResponse>(`/api/v1/consult/${traceId}`);
}

export async function listConsultations(
  limit = 20,
): Promise<ConsultationSummary[]> {
  return apiFetch<ConsultationSummary[]>(`/api/v1/consult?limit=${limit}`);
}

export function getComparativeExportUrl(traceId: string): string {
  return `${API_BASE}/api/v1/consult/${traceId}/export/comparative`;
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
