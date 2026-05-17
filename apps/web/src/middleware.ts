import { NextResponse, type NextRequest } from "next/server";

function safeOrigin(raw: string): string {
  if (!raw) return "";
  try {
    return new URL(raw).origin;
  } catch {
    return "";
  }
}

export function middleware(request: NextRequest) {
  // Edge-compatible nonce (no Node.js crypto)
  const array = new Uint8Array(16);
  crypto.getRandomValues(array);
  const nonce = Array.from(array, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  );

  const grafanaUrl = safeOrigin(process.env.NEXT_PUBLIC_GRAFANA_URL ?? "");
  const langfuseUrl = safeOrigin(process.env.NEXT_PUBLIC_LANGFUSE_URL ?? "");
  const jaegerUrl = safeOrigin(process.env.NEXT_PUBLIC_JAEGER_URL ?? "");
  const apiUrl = safeOrigin(process.env.NEXT_PUBLIC_API_URL ?? "");

  const frameSrcOrigins = [grafanaUrl, langfuseUrl, jaegerUrl]
    .filter(Boolean)
    .join(" ");

  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    "style-src 'self' 'unsafe-inline'", // Tailwind v4 runtime injection
    "img-src 'self' data: https:",
    "font-src 'self'",
    "frame-ancestors 'none'",
    frameSrcOrigins
      ? `frame-src 'self' ${frameSrcOrigins}`
      : "frame-src 'self'",
    apiUrl ? `connect-src 'self' ${apiUrl}` : "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  // CSP must also be on the request headers so Next.js detects it during SSR
  // and automatically injects the nonce into <script> tags it generates.
  // Without this, strict-dynamic + nonce blocks every Next.js bundle and the
  // page renders blank under <main> (only the layout shell shows up).
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: "/((?!_next/static|_next/image|favicon.ico).*)",
};
