# Fuente: FCA Handbook

## URL base

```
https://www.handbook.fca.org.uk/
```

## Nota técnica importante

**FCA Handbook no tiene API XML pública** (verificado 2026-05-11). El contenido se sirve mediante HTML con renderizado parcial JavaScript. La implementación actual realiza scraping HTML estático; algunas secciones pueden requerir renderizado completo para obtener el texto íntegro.

## Secciones cubiertas

| Código | Nombre completo                                      | URL              |
| ------ | ---------------------------------------------------- | ---------------- |
| PRIN   | Principles for Businesses                            | `/handbook/PRIN` |
| COBS   | Conduct of Business Sourcebook                       | `/handbook/COBS` |
| SYSC   | Senior Management Arrangements, Systems and Controls | `/handbook/SYSC` |

Para ampliar la cobertura, añadir entradas a `COVERED_SECTIONS` en `fca.py`.

## Términos de uso consultados

**Fecha de consulta:** 2026-05-11

- El FCA Handbook es un documento regulatorio oficial publicado por la Financial Conduct Authority.
- Se publica bajo **Open Government Licence v3.0 (OGL v3)**.
- El uso, reproducción y distribución están permitidos con atribución.
- No existe declaración de prohibición de scraping en `robots.txt` para páginas del Handbook.

## Rate limit aplicado

**1 req / 2 s** (`rate_limit_rps = 0.5`), por respeto al servidor público y conforme a ADR 0011.

## User-Agent utilizado

```
lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)
```

## Formato de datos esperado

- **Tipo:** HTML (scraping únicamente)
- **Identificador:** código de sección o `{SECCIÓN}/{capítulo}`, e.g. `PRIN`, `COBS/2`
- **Campos extraídos:**
  - `title`: del `<h1>` o metadato de sección
  - `publication_date`: de elemento "last updated" o `<time>` (fallback a `date.today()`)
  - `hierarchy`: reglas identificadas por headings `h2`/`h3` con números de regla
  - `full_text`: texto extraído del contenedor `<div class="content/handbook/rules">`, `<article>` o `<main>`
  - `extra.section`: código de sección (PRIN, COBS, SYSC)

## Detección de cambios de formato

| Señal                                                                | Causa probable                                                                         |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `full_text` muy corto (<500 chars) para secciones extensas           | El FCA ha migrado a contenido renderizado por JavaScript; necesita Playwright/Selenium |
| `hierarchy` vacío                                                    | Los headings ya no usan `h2`/`h3` o la numeración ha cambiado de formato               |
| `list_documents()` devuelve sólo secciones principales sin capítulos | La estructura de TOC HTML ha cambiado                                                  |
| HTTP 403                                                             | El FCA ha implementado protección anti-bot                                             |

**Limitación conocida:** cobertura parcial. El Handbook completo tiene decenas de sourcebooks; esta implementación cubre el mínimo requerido para el MVP bancario.
