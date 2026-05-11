# Fuente: EDPB Guidelines and Opinions

## URL base

```
https://www.edpb.europa.eu/our-work-tools/our-documents_en
```

Documentos individuales (landing page):
```
https://www.edpb.europa.eu/our-work-tools/our-documents/guidelines/<slug>_en
```

PDF descargable enlazado desde la página de cada documento.

## Términos de uso consultados

**Fecha de consulta:** 2026-05-11

- Los documentos del EDPB se publican bajo **Creative Commons Attribution 4.0 International (CC BY 4.0)**.
- Uso, reproducción, transformación y distribución permitidos con atribución.
- No requiere autorización adicional para uso interno no comercial.
- El scraping HTML de la página pública es compatible con los términos.
- **Nota ADR 0011:** PDFs son excepción explícita a la regla anti-PDF porque tienen estructura consistente (secciones numeradas, footers estándar).

## Rate limit aplicado

**1 req / 2 s** (`rate_limit_rps = 0.5`), conforme a ADR 0011.

## User-Agent utilizado

```
lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)
```

## Formato de datos esperado

- **Tipo:** PDF (extracción con `pdfminer.six`); fallback a `content_type="pdf"` con bytes crudos si pdfminer no está instalado
- **Identificador:** slug de URL, e.g. `guidelines-012023`
- **Campos extraídos:**
  - `title`: primera línea no vacía del texto PDF, o `<h1>` de la página HTML
  - `publication_date`: del elemento `<time>` de la página de landing
  - `type`: `guideline` o `opinion` inferido del slug
  - `full_text`: texto completo extraído del PDF

## Detección de cambios de formato

| Señal | Causa probable |
|-------|----------------|
| `full_text` vacío cuando `content_type="pdf"` | `pdfminer.six` no instalado o PDF escaneado/cifrado |
| `list_documents()` devuelve 0 IDs | La URL `/our-work-tools/our-documents_en` ha cambiado o la estructura de links ha variado |
| `title` = primera línea del PDF es un header/footer en lugar del título real | La maquetación del PDF ha cambiado |
| Error HTTP 404 en descarga de PDF | La URL del PDF ha rotado (el EDPB reestructura ocasionalmente sus URLs) |

**Dependencia externa:** `pdfminer.six` (opcional, no en `pyproject.toml`). Instalar manualmente si se requiere extracción completa: `pip install pdfminer.six`.
