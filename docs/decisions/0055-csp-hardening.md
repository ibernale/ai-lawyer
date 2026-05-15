# 0055 — CSP Hardening: Nonce-based Policy + HSTS

**Status:** Accepted
**Date:** 2026-05-15

## Context

The pre-Fase-10.4 CSP used `'unsafe-inline'` and `'unsafe-eval'` in `script-src`,
which provided minimal protection against XSS. The policy was also static (baked
into `next.config.mjs` `headers()`) making it impossible to use nonces. HSTS was
absent from both the Next.js frontend and the FastAPI backend. Referrer-Policy was
`strict-origin` (omits path for cross-origin) instead of the safer
`strict-origin-when-cross-origin`.

## Decision

### Next.js: nonce-based dynamic CSP

A Next.js middleware (`apps/web/src/middleware.ts`) generates a per-request
16-byte cryptographic nonce (via `crypto.getRandomValues` — Edge Runtime
compatible). The nonce is:

- Embedded in the `script-src 'nonce-{nonce}' 'strict-dynamic'` directive
- Forwarded to SSR components via the `x-nonce` request header

`'strict-dynamic'` allows scripts loaded by nonce-carrying scripts, so
third-party loaders do not need explicit allow-listing.

The static CSP entry in `next.config.mjs` `headers()` is removed; the
middleware handles it dynamically on every request.

```
script-src 'self' 'nonce-{random}' 'strict-dynamic'
style-src 'self' 'unsafe-inline'    ← Tailwind v4 injects styles at runtime
frame-src 'self' {grafana} {langfuse} {jaeger}
connect-src 'self' {NEXT_PUBLIC_API_URL}
object-src 'none'
base-uri 'self'
frame-ancestors 'none'
```

### HSTS

Both the Next.js frontend (`next.config.mjs`) and the FastAPI API
(`middleware.py`) add:

```
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
```

This ensures all future connections use HTTPS for one year, including subdomains.
The `preload` directive enables submission to the HSTS preload list.

### Other header hardening

| Header               | Before           | After                                                                          |
| -------------------- | ---------------- | ------------------------------------------------------------------------------ |
| `Referrer-Policy`    | `strict-origin`  | `strict-origin-when-cross-origin`                                              |
| `Permissions-Policy` | camera, mic, geo | + usb, payment, serial, bluetooth, xr-spatial-tracking, screen-wake-lock, midi |
| `X-XSS-Protection`   | `1; mode=block`  | Removed (deprecated; CSP supersedes it)                                        |

### Rate limiting on `/auth/token`

`slowapi` decorator `@limiter.limit("10/minute", key_func=ip)` on `POST /auth/token`
provides brute-force protection. The limiter uses client IP (not user ID) so it
applies before credential validation.

The limiter is extracted to `lex_agents_api/limiter.py` to avoid circular imports
when routers import it independently of `main.py`.

## Consequences

- All `<script>` tags in SSR pages must carry the `nonce` attribute. Client
  components injecting scripts inline must retrieve the nonce from the
  `x-nonce` header.
- `'unsafe-eval'` is removed — dynamic `eval()` will be blocked.
- The Grafana, Langfuse, and Jaeger URLs must be set in `NEXT_PUBLIC_*` env vars
  for the `frame-src` directive to include them.
- HSTS `preload` requires the domain to be registered at hstspreload.org before
  production deployment.

## Alternatives considered

- **Static CSP with hash-based nonces**: Less flexible; requires computing hashes
  at build time. Nonces are simpler for Next.js SSR.
- **Report-only mode first**: Useful for auditing but adds latency to ship.
  Internal platform → enforce immediately.
- **CSP Level 2 without `strict-dynamic`**: Would require maintaining an explicit
  script allow-list. `strict-dynamic` is supported by all modern browsers.
