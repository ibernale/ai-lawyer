# Branding

## Logo

The `Logo` component (`apps/web/src/components/Logo.tsx`) renders the Lex Agents
mark in the admin sidebar. By default it shows an SVG placeholder with the "LA"
initials in brand red (`#EC0000`).

### Override with a custom logo

Set the `NEXT_PUBLIC_LOGO_URL` environment variable to any image URL:

```bash
# .env.local
NEXT_PUBLIC_LOGO_URL=https://your-cdn.example.com/logo.png
```

The image is rendered at `120×32px` (full variant) or `32×32px` (icon variant).
Recommended formats: SVG or 2× PNG with transparent background.

### Placeholder SVG

`placeholder-logo.svg` — reference file showing the approved layout:
red square with white "LA" initials + "Lex Agents" logotype in `#1A1A1A`.

This SVG is not loaded at runtime; it is documentation only. The `Logo` component
renders an equivalent layout inline when no `NEXT_PUBLIC_LOGO_URL` is set.

## Color palette

Primary: `#EC0000` (Santander red). Full palette in `docs/design-system.md`.
