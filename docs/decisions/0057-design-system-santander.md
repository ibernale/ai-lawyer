# 0057 — Design system Santander

**Status:** Accepted  
**Date:** 2026-05-15

## Context

El frontend actual (`apps/web/`) usa Tailwind CSS con la paleta por defecto
y shadcn/ui como base de componentes. No existe un sistema de tokens de diseño
alineado con la identidad visual de Santander ni una biblioteca de componentes
coherente para las nuevas secciones que introducen las sub-fases 10.1–10.3
(gestión de usuarios, onboarding, integración AWS).

La plataforma opera en el contexto de Grupo Santander. Aunque los assets de
marca oficiales requieren aprobación formal (ver ADR 0058), la paleta
corporativa es información pública que puede aplicarse desde ya. El resultado
debe ser una interfaz reconociblemente bancaria y profesional, con un sistema
de tokens que permita sustituir el branding placeholder por el oficial cuando
llegue la aprobación sin refactoring de componentes.

## Decision

### Design tokens

Los tokens se implementan como variables CSS (compatible con Tailwind v3
`extend.colors` y con CSS nativo). Se definen en `apps/web/src/styles/tokens.css`.

#### Paleta primaria (corporativa Santander pública)

| Token                    | Valor     | Uso                              |
|--------------------------|-----------|----------------------------------|
| `--color-santander-red`  | `#EC0000` | Primario, CTAs principales       |
| `--color-santander-red-dark` | `#B30000` | Hover, énfasis             |
| `--color-santander-red-light` | `#FF4444` | Highlights sutiles        |
| `--color-santander-white` | `#FFFFFF` | Fondos, superficies              |
| `--color-santander-black` | `#1A1A1A` | Texto principal                  |
| `--color-gray-900`       | `#2C2C2C` | Texto secundario                 |
| `--color-gray-700`       | `#4A4A4A` | Texto terciario, iconos          |
| `--color-gray-500`       | `#767676` | Placeholders, texto desactivado  |
| `--color-gray-300`       | `#C9C9C9` | Bordes, divisores                |
| `--color-gray-100`       | `#F5F5F5` | Fondos de secciones              |

#### Colores semánticos

| Token               | Valor     | Nota                                        |
|---------------------|-----------|---------------------------------------------|
| `--color-success`   | `#2E7D32` | Verde WCAG AA sobre blanco                  |
| `--color-warning`   | `#ED6C02` | Naranja estándar accesible                  |
| `--color-error`     | `#D32F2F` | Variante del rojo institucional             |
| `--color-info`      | `#0288D1` | Azul informativo neutro                     |

#### Tipografía

```css
--font-primary: 'Inter', system-ui, sans-serif;
--font-mono: 'JetBrains Mono', 'Fira Code', monospace;
```

Inter es open-source (SIL OFL 1.1), disponible en Google Fonts. Sus métricas
son similares a Santander Text, lo que facilita la sustitución si Marca
Santander decide proveer la fuente corporativa.

Escala de tamaños (ratio modular 1.25):

| Variable        | Valor   | Uso típico                |
|-----------------|---------|---------------------------|
| `--text-xs`     | `0.64rem` | Labels, metadata        |
| `--text-sm`     | `0.8rem`  | Texto auxiliar          |
| `--text-base`   | `1rem`    | Cuerpo de texto         |
| `--text-lg`     | `1.25rem` | Subtítulos              |
| `--text-xl`     | `1.563rem`| Títulos de sección      |
| `--text-2xl`    | `1.953rem`| Títulos de página       |
| `--text-3xl`    | `2.441rem`| Headings principales    |

Pesos disponibles: 400 (regular), 500 (medium), 600 (semibold), 700 (bold).

#### Espaciado

Escala base 4px:

| Variable   | Valor  |
|------------|--------|
| `--space-1` | `4px` |
| `--space-2` | `8px` |
| `--space-3` | `12px` |
| `--space-4` | `16px` |
| `--space-6` | `24px` |
| `--space-8` | `32px` |
| `--space-12`| `48px` |
| `--space-16`| `64px` |

#### Border radius

Conservador (banking-appropriate; sin exceso de redondeo que pueda parecer
informal):

| Variable          | Valor  | Uso                            |
|-------------------|--------|--------------------------------|
| `--radius-sm`     | `4px`  | Inputs, badges, chips          |
| `--radius-base`   | `8px`  | Cards, containers              |
| `--radius-lg`     | `12px` | Modals, drawers                |
| `--radius-full`   | `9999px` | Avatares, pills              |

#### Sombras

Paleta sutil; sin sombras dramáticas que resulten visualmente ruidosas en
un contexto de datos jurídicos densos:

```css
--shadow-sm:  0 1px 2px rgba(0,0,0,0.06);
--shadow-base: 0 2px 8px rgba(0,0,0,0.08);
--shadow-lg:  0 4px 16px rgba(0,0,0,0.12);
```

### Componente `<Logo />`

Ubicación: `apps/web/src/components/brand/Logo.tsx`

- Acepta props `size` (sm/md/lg) y `variant` (default/mono/white).
- Por defecto renderiza un placeholder SVG: rectángulo con el texto
  "lex-agents" en `--color-gray-500` sobre fondo `--color-gray-100`.
- Configurable sin recompilar via variables de entorno:
  - `NEXT_PUBLIC_BRAND_LOGO_SRC`: URL del asset SVG/PNG del logo.
  - `NEXT_PUBLIC_BRAND_NAME`: nombre que aparece en el `<title>` del
    documento y en el texto alternativo del logo.
- Cuando Marca Santander apruebe los assets (ADR 0058), se sustituye el
  placeholder con el SVG oficial sin tocar ningún otro componente.

### Dark mode

Opcional; desactivado por defecto en Fase 10. El sistema de tokens define
un segundo set de valores bajo el selector `[data-theme="dark"]`:

```css
[data-theme="dark"] {
  --color-santander-white: #1A1A1A;
  --color-santander-black: #F5F5F5;
  /* ... resto de la paleta invertida */
}
```

El toggle de dark mode se añade en la barra de configuración del usuario.
No se activa automáticamente mediante `prefers-color-scheme` en Fase 10
para mantener el branding controlado.

### Accesibilidad

Requisitos no negociables:

- **WCAG 2.1 AA mínimo** en todos los pares texto/fondo. Verificado con
  herramienta automatizada en CI (axe-core o similar).
- **Focus visible** en todos los elementos interactivos:
  `outline: 2px solid var(--color-santander-red); outline-offset: 2px`.
- **Navegación completa por teclado**: todos los flujos (login, consulta,
  onboarding, admin) son completables sin ratón.
- **Aria labels** en componentes complejos (Notifications drawer, iframe
  embeddings, modales de confirmación).
- **Skip links**: `<a href="#main-content">Ir al contenido principal</a>`
  visible on focus en todos los layouts.
- **No información solo por color**: estados de éxito/error acompañados
  siempre de texto o icono además del color.

### Documentación

`docs/design-system.md` documenta todos los tokens, ejemplos de uso,
componentes disponibles y guidelines de aplicación. Se crea como parte
de la sub-fase 10.1.

## Alternatives considered

**shadcn/ui vanilla (sin tokens personalizados):**

- Pro: menos trabajo inicial; shadcn/ui ya está en el proyecto.
- Con: sin tokens, cada componente nuevo reproduce la paleta ad-hoc y la
  consistencia visual se degrada con el tiempo. No hay ruta clara hacia el
  branding Santander oficial.
- Rechazado: los tokens son el requisito mínimo para una plataforma corporativa.

**Ant Design:**

- Pro: sistema de diseño maduro con componentes bancarios.
- Con: opinionated y pesado; personalización de tokens requiere overrides
  complejos en Less/LESS variables. Dificultad de integración con Tailwind.
- Rechazado.

**Material UI:**

- Pro: ecosistema amplio, bien documentado.
- Con: estética Google, no bancaria. Requiere personalización profunda para
  parecerse a Santander. Bundle size significativo.
- Rechazado.

**Contratar diseño a una agencia externa:**

- Pro: resultado profesional garantizado.
- Con: tiempo y coste no justificados para un MVP interno.
- Rechazado para Fase 10; puede ser relevante para el rollout a producción Santander.

## Consequences

**Positivo:**

- Token system permite sustituir el branding placeholder por el oficial
  en un único fichero (`tokens.css`) sin refactoring de componentes.
- Inter es una fuente de alta calidad, open-source y con excelente legibilidad
  en pantalla — especialmente relevante para texto jurídico denso.
- La escala de espaciado 4px es compatible con la grid de Tailwind (múltiplos
  de 4px), por lo que los tokens se traducen directamente a clases Tailwind.
- El sistema de accesibilidad cumple los requisitos legales de la Directiva
  Europea de Accesibilidad (EN 301 549) aplicables a sistemas internos.

**Negativo:**

- Requiere auditoría de los componentes existentes para alinearlos con los
  nuevos tokens (trabajo en sub-fase 10.1).
- `docs/design-system.md` es documentación que debe mantenerse actualizada
  con cada nuevo componente; si se descuida se vuelve stale.
- La prohibición de `prefers-color-scheme` automático puede ser criticada por
  usuarios que esperan que su preferencia de sistema operativo se respete.
  Es un compromiso consciente para mantener el branding controlado.
