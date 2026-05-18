/** @type {import('next').NextConfig} */

import createNextIntlPlugin from "next-intl/plugin";

// next-intl v3.26.x writes its Turbopack alias to experimental.turbo.resolveAlias
// (Next.js 15 API). Next.js 16 reads it from the stable turbopack.resolveAlias key.
// Having a top-level `turbopack:` block in nextConfig causes Next.js 16 to activate
// Turbopack for `next build`, setting process.env.TURBOPACK — which makes the plugin
// take the broken Turbopack path instead of the working webpack path.
//
// Fix: remove the turbopack block so next build uses webpack (the default).
// next-intl's webpack integration (l.context-relative path resolution) works
// correctly without any extra configuration.
// If Turbopack is needed for local dev, run: NEXT_TURBOPACK=1 next dev (or --turbo).
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

// ALB routing handles API path dispatch (no Next.js rewrites needed):
//   /health, /version        → FastAPI (ALB priority 15)
//   /auth/*                  → FastAPI (ALB priority 20)
//   /api/v1/*                → FastAPI (ALB priority 25)
//   /*                       → Next.js (ALB priority 100)
// Browser uses relative paths ("") so no URL is baked in the image.
// Server-side (SSR) uses process.env.API_BASE_URL (runtime, set in ECS task def).

const API_UPSTREAM = process.env.API_BASE_URL ?? "http://localhost:8000";

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

    // next-intl v3.26.x writes its Turbopack alias to experimental.turbo.resolveAlias
    // (Next.js 15 stable API). Next.js 16 uses Turbopack as the default bundler and
    // reads aliases from turbopack.resolveAlias (the promoted stable key). The plugin
    // never updates the stable key, so the alias is silently missing and every SSR
    // request crashes with "Couldn't find next-intl config file".
    //
    // Fix: register the alias manually at the correct key. The plugin still writes to
    // experimental.turbo (harmlessly). Next.js 16 Turbopack resolves relative paths
    // in resolveAlias relative to next.config.mjs (apps/web), so this resolves
    // correctly to apps/web/src/i18n/request.ts without needing turbopack.root.
    turbopack: {
        resolveAlias: {
            "next-intl/config": "./src/i18n/request.ts",
        },
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
