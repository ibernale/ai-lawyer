/** @type {import('next').NextConfig} */

// ALB routing handles API path dispatch (no Next.js rewrites needed):
//   /health, /version        → FastAPI (ALB priority 15)
//   /auth/*                  → FastAPI (ALB priority 20)
//   /api/v1/*                → FastAPI (ALB priority 25)
//   /*                       → Next.js (ALB priority 100)
// Browser uses relative paths ("") so no URL is baked in the image.
// Server-side (SSR) uses process.env.API_BASE_URL (runtime, set in ECS task def).

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

export default nextConfig;
