/** @type {import('next').NextConfig} */

// ALB routing handles API path dispatch (no Next.js rewrites needed):
//   /health, /version        → FastAPI (ALB priority 15)
//   /auth/*                  → FastAPI (ALB priority 20)
//   /api/v1/*                → FastAPI (ALB priority 25)
//   /*                       → Next.js (ALB priority 100)
// Browser uses relative paths ("") so no URL is baked in the image.
// Server-side (SSR) uses process.env.API_BASE_URL (runtime, set in ECS task def).

// Frame-src allow-list: populated from NEXT_PUBLIC_* env vars at build time.
// In local dev, localhost ports are also allowed (Grafana :3001, Jaeger :16686).
const _frameSrcOrigins = [
  process.env.NEXT_PUBLIC_GRAFANA_URL,
  process.env.NEXT_PUBLIC_LANGFUSE_URL,
  process.env.NEXT_PUBLIC_JAEGER_URL,
  process.env.NODE_ENV === "development" ? "http://localhost:3001" : "",
  process.env.NODE_ENV === "development" ? "http://localhost:3002" : "",
  process.env.NODE_ENV === "development" ? "http://localhost:16686" : "",
]
  .filter(Boolean)
  .join(" ");

const _frameSrc = _frameSrcOrigins
  ? `frame-src 'self' ${_frameSrcOrigins};`
  : "frame-src 'self';";

const nextConfig = {
  output: "standalone",
  typedRoutes: true,

  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          { key: "X-XSS-Protection", value: "1; mode=block" },
          {
            key: "Content-Security-Policy",
            // connect-src 'self' is enough: all browser → API calls are relative paths
            // proxied by Next.js rewrites; no direct cross-origin calls needed.
            // frame-src allows embedded observability tools (Grafana, Langfuse, Jaeger).
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob:",
              "font-src 'self'",
              "frame-ancestors 'none'",
              "connect-src 'self'",
              _frameSrc,
            ].join("; "),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
