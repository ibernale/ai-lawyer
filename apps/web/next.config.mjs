/** @type {import('next').NextConfig} */

import createNextIntlPlugin from "next-intl/plugin";
import { fileURLToPath } from "url";
import path from "path";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

// Resolve the monorepo root relative to this config file so Turbopack uses
// the worktree root instead of the parent repo when multiple pnpm-workspace.yaml
// files are present on the filesystem.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");

// ALB routing handles API path dispatch (no Next.js rewrites needed):
//   /health, /version        → FastAPI (ALB priority 15)
//   /auth/*                  → FastAPI (ALB priority 20)
//   /api/v1/*                → FastAPI (ALB priority 25)
//   /*                       → Next.js (ALB priority 100)
// Browser uses relative paths ("") so no URL is baked in the image.
// Server-side (SSR) uses process.env.API_BASE_URL (runtime, set in ECS task def).

const API_UPSTREAM =
    process.env.API_BASE_URL ?? "http://localhost:8000";

const nextConfig = {
    output: "standalone",
    typedRoutes: true,

    // Ensure messages JSON files are traced and included in the standalone
    // output. The static import map in src/i18n/request.ts already makes
    // webpack bundle them, but this is an explicit safety net so they are
    // also available as raw files (e.g. for any runtime fs reads).
    outputFileTracingIncludes: {
        "/**": ["./messages/**"],
    },

    turbopack: {
        root: repoRoot,
    },

    // In production the ALB routes /api/v1/*, /health, /version, /auth/* to
    // FastAPI before the request reaches Next.js — rewrites never fire there.
    // In local dev (no Docker/ALB) these rewrites proxy the browser calls.
    async rewrites() {
        return [
            {
                source: "/api/v1/:path*",
                destination: `${API_UPSTREAM}/api/v1/:path*`,
            },
            {
                source: "/health",
                destination: `${API_UPSTREAM}/health`,
            },
            {
                source: "/version",
                destination: `${API_UPSTREAM}/version`,
            },
            {
                source: "/auth/:path*",
                destination: `${API_UPSTREAM}/auth/:path*`,
            },
        ];
    },

    async headers() {
        return [
            {
                source: "/(.*)",
                headers: [
                    { key: "X-Frame-Options", value: "DENY" },
                    { key: "X-Content-Type-Options", value: "nosniff" },
                    {
                        key: "Strict-Transport-Security",
                        value: "max-age=31536000; includeSubDomains; preload",
                    },
                    {
                        key: "Referrer-Policy",
                        value: "strict-origin-when-cross-origin",
                    },
                    {
                        key: "Permissions-Policy",
                        value: "camera=(), microphone=(), geolocation=(), usb=(), payment=(), serial=(), bluetooth=(), xr-spatial-tracking=(), screen-wake-lock=(), midi=()",
                    },
                    // X-XSS-Protection omitted — deprecated in modern browsers
                    // Content-Security-Policy injected per-request by middleware.ts (nonce-based)
                ],
            },
        ];
    },
};

export default withNextIntl(nextConfig);
