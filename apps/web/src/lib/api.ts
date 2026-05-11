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
// Fetch helpers
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
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
): Promise<ConsultResponse> {
  return apiFetch<ConsultResponse>("/api/v1/consult", {
    method: "POST",
    body: JSON.stringify({
      query,
      output_type: outputType ?? null,
      jurisdiction_hint: jurisdictionHint ?? null,
    }),
  });
}

export async function getConsultation(traceId: string): Promise<ConsultResponse> {
  return apiFetch<ConsultResponse>(`/api/v1/consult/${traceId}`);
}

export async function listConsultations(limit = 20): Promise<ConsultationSummary[]> {
  return apiFetch<ConsultationSummary[]>(`/api/v1/consult?limit=${limit}`);
}
