# 0053 — Design System: Token Architecture

**Status:** Accepted
**Date:** 2026-05-15

## Context

The admin panel was using a generic navy palette (`#243b53`) not aligned with the
Santander corporate brand. There was no systematic approach to design tokens —
colors were scattered across Tailwind classes throughout components.

With the platform moving toward production usage inside Santander, visual identity
consistency and a maintainable token system became necessary.

## Decision

Use CSS custom properties in the `@theme` block of `globals.css` (Tailwind v4
approach — no `tailwind.config.ts`). CVA (`class-variance-authority`) for
component variant logic. No shadcn/ui — it generates files that diverge from repo
conventions; we prefer CVA directly over plain HTML elements or lightweight
primitives.

**Santander brand red palette (primary):**
- `brand-500`: `#EC0000` — primary color for buttons, active states, links
- `brand-700`: `#B30000` — inline text on white (WCAG AA safe: 7.25:1 ratio)
- `brand-900`: `#6B0000` — darkest, for high-contrast uses

**Sidebar:** `#1A1A1A` (neutral black) replaces the former `bg-gray-900`.
Active nav items use `bg-primary` (brand red).

**Components created:**
- `button.tsx`, `input.tsx`, `card.tsx`, `alert.tsx`, `tabs.tsx` — CVA pattern
- `Logo.tsx` — configurable via `NEXT_PUBLIC_LOGO_URL`, fallback to "LA" initials
- `PageLayout.tsx` — admin page wrapper
- `badge.tsx` — updated with `brand` variant

## Consequences

- Token changes are centralized: updating the brand = editing `globals.css`.
- Components are individually testable via Vitest.
- `lucide-react` added as icon dependency.
- Existing pages using hardcoded Tailwind color classes still work (backward
  compatible); new pages should use semantic tokens.

## Alternatives considered

- **shadcn/ui**: Generates copied files that drift; rejected.
- **Tailwind CSS theme extension in config**: Not applicable in Tailwind v4.
- **CSS-in-JS (Emotion/styled-components)**: No SSR benefit here; adds bundle weight.
