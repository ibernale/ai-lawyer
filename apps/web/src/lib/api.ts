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
    const body = new URLSearchParams({ username: "demo", password: "demo1234" });
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
  const isAuthEndpoint = path.startsWith("/health") || path.startsWith("/version");
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
      if (!retry.ok) throw new Error(`API error ${retry.status}: ${retry.statusText}`);
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
): Promise<ConsultResponse> {
  return apiFetch<ConsultResponse>("/api/v1/consult", {
    method: "POST",
    body: JSON.stringify({
      query,
      output_type: outputType ?? null,
      jurisdiction_hint: jurisdictionHint ?? null,
      depth: depth ?? null,
    }),
  });
}

export async function getConsultation(traceId: string): Promise<ConsultResponse> {
  return apiFetch<ConsultResponse>(`/api/v1/consult/${traceId}`);
}

export async function listConsultations(limit = 20): Promise<ConsultationSummary[]> {
  return apiFetch<ConsultationSummary[]>(`/api/v1/consult?limit=${limit}`);
}
