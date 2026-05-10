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
