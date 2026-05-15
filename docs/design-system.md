# Lex Agents — Design System

Santander brand palette applied to the admin panel. Tokens defined in
`apps/web/src/app/globals.css`. Component patterns in
`apps/web/src/components/ui/`.

See [`docs/decisions/0053`](decisions/0053-design-system-tokens.md) and
[`docs/decisions/0054`](decisions/0054-wcag-aa-compliance.md) for the rationale.

---

## Color palette

### Brand red (primary)

| Token | Hex | Use |
|-------|-----|-----|
| `brand-50` | `#fff0f0` | Hover backgrounds, light fills |
| `brand-100` | `#ffd6d6` | Light fills, info banners |
| `brand-200` | `#ffadad` | Borders on light backgrounds |
| `brand-300` | `#ff7070` | Interactive accents |
| `brand-400` | `#ff3333` | Hover on primary |
| **`brand-500`** | **`#EC0000`** | **PRIMARY — buttons, active states** |
| `brand-600` | `#cc0000` | Active/pressed primary |
| `brand-700` | `#b30000` | Text on white (WCAG AA: 7.25:1) |
| `brand-800` | `#8f0000` | High-contrast text |
| `brand-900` | `#6b0000` | Darkest, use sparingly |

### Semantic tokens (`:root` CSS vars)

| Variable | Value | Use |
|----------|-------|-----|
| `--primary` | `#EC0000` | Brand color |
| `--primary-foreground` | `#FFFFFF` | Text on primary |
| `--destructive` | red-600 | Error actions |
| `--ring` | `#EC0000` | Focus ring |

### Layout

| Color | Hex | Use |
|-------|-----|-----|
| Sidebar background | `#1A1A1A` | Admin sidebar |
| Sidebar active | `var(--primary)` | Active nav item |
| Page background | `#F8F9FA` | Admin content area |
| Surface | `#FFFFFF` | Cards, panels |

---

## Typography

| Scale | Class | Use |
|-------|-------|-----|
| Page title | `text-xl font-semibold` | `<h1>` in `PageLayout` |
| Section title | `text-sm font-semibold` | Card headers |
| Body | `text-sm` | General content |
| Small / label | `text-xs` | Badges, meta |
| Mono | `font-mono text-xs` | Code, IDs, hashes |

Font: Inter (sans), JetBrains Mono (code).

---

## Components

### Button

```tsx
import { Button } from "@/components/ui/button";

<Button variant="default">Guardar</Button>
<Button variant="destructive">Eliminar</Button>
<Button variant="outline">Cancelar</Button>
<Button variant="ghost">Ver más</Button>
<Button loading>Procesando...</Button>
```

Variants: `default` (brand red), `secondary`, `destructive`, `outline`, `ghost`, `link`.
Sizes: `sm`, `md` (default), `lg`, `icon`.

### Badge

```tsx
import { Badge } from "@/components/ui/badge";

<Badge variant="default">Admin</Badge>
<Badge variant="brand">Activo</Badge>
<Badge variant="success">OK</Badge>
<Badge variant="warning">Pendiente</Badge>
<Badge variant="error">Error</Badge>
```

### Alert

```tsx
import { Alert } from "@/components/ui/alert";

<Alert variant="info" title="Información">Mensaje informativo.</Alert>
<Alert variant="success">Operación completada.</Alert>
<Alert variant="warning">Revisa los datos.</Alert>
<Alert variant="error">Ha ocurrido un error.</Alert>
```

### Card

```tsx
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";

<Card>
  <CardHeader>
    <CardTitle>Título</CardTitle>
    <CardDescription>Descripción opcional</CardDescription>
  </CardHeader>
  <CardContent>
    {/* contenido */}
  </CardContent>
</Card>
```

### Tabs

```tsx
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

<Tabs defaultValue="tab1">
  <TabsList>
    <TabsTrigger value="tab1">Pestaña 1</TabsTrigger>
    <TabsTrigger value="tab2">Pestaña 2</TabsTrigger>
  </TabsList>
  <TabsContent value="tab1">Contenido 1</TabsContent>
  <TabsContent value="tab2">Contenido 2</TabsContent>
</Tabs>
```

### Input

```tsx
import { Input } from "@/components/ui/input";

<Input placeholder="Buscar..." />
<Input error errorId="err-name" aria-label="Nombre" />
<p id="err-name" className="text-xs text-red-600">Campo obligatorio</p>
```

### PageLayout

```tsx
import { PageLayout } from "@/components/admin/PageLayout";

<PageLayout
  title="Feature Flags"
  description="Gestión de flags en tiempo real."
  actions={<Button>Nuevo flag</Button>}
>
  {/* contenido de la página */}
</PageLayout>
```

### Logo

```tsx
import { Logo } from "@/components/Logo";

<Logo variant="full" />   // "LA" icon + "Lex Agents" text
<Logo variant="icon" />   // solo icono "LA"
```

Override logo via `NEXT_PUBLIC_LOGO_URL` env var (any image URL).

---

## WCAG 2.1 AA — contrast summary

| Combination | Ratio | Pass? |
|-------------|-------|-------|
| White text on `#EC0000` button | 4.48:1 | ✓ (UI component + large bold text) |
| `#B30000` on white (inline text) | 7.25:1 | ✓ |
| White on `#1A1A1A` sidebar | 16.1:1 | ✓ |
| `#6C757D` on white (secondary text) | 4.60:1 | ✓ |

**Never use `#EC0000` for body text on white** — use `#B30000` for inline links.
