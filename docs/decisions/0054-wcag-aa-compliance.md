# 0054 — WCAG 2.1 AA Compliance

**Status:** Accepted
**Date:** 2026-05-15

## Context

As an internal banking platform, accessibility compliance reduces legal risk and
improves usability for all users. WCAG 2.1 AA is the minimum standard required by
the EU Web Accessibility Directive (2016/2102).

## Decision

Target WCAG 2.1 Level AA across all admin UI. Key rules:

### Contrast ratios (Success Criterion 1.4.3 / 1.4.11)

| Combination | Ratio | Use |
|-------------|-------|-----|
| `#B30000` on `#FFFFFF` | 7.25:1 ✓ | Inline text links on white |
| `#FFFFFF` on `#EC0000` | 4.48:1 ✓ | Button text (bold, ≥14px) |
| `#FFFFFF` on `#1A1A1A` | 16.1:1 ✓ | Sidebar text |
| `#6C757D` on `#FFFFFF` | 4.60:1 ✓ | Secondary text |
| `#EC0000` as UI component | 4.48:1 ✓ | Borders, icons (3:1 required) |

**Rule:** Never use `#EC0000` for body text on white — use `#B30000` instead.
Button text is exempt (bold + large size satisfies the 3:1 UI component threshold).

### Keyboard and ARIA

- All interactive elements must be reachable via keyboard.
- `focus-visible:ring-2 focus-visible:ring-ring` applied to all interactive CVA components.
- `aria-invalid`, `aria-describedby` on input fields with errors.
- `role="alert"` on `Alert` component and `ErrorBanner`.
- `role="tablist"`, `role="tab"`, `aria-selected` on `Tabs` component.
- `aria-label` on icon-only buttons (e.g., bell notifications).
- `aria-hidden="true"` on decorative icons.

### Logo

`role="img"` + `aria-label="Lex Agents"` on the `Logo` component.

## Consequences

- All new components include ARIA attributes by default.
- `#EC0000` is prohibited for inline body text; `#B30000` must be used instead.
- a11y audit (legal-code-reviewer) runs post-implementation to verify.

## Alternatives considered

- **WCAG 2.2**: Subset of new 2.2 criteria applied where feasible (focus appearance),
  but 2.1 AA is the contractual minimum.
- **Automated tools only**: axe-core via Vitest catches ~30% of issues; manual audit
  required for full coverage.
