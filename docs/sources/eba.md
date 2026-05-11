# Fuente: EBA Single Rulebook Q&As

## URL base

```
https://www.eba.europa.eu/single-rule-book-qa
```

## Términos de uso consultados

**Fecha de consulta:** 2026-05-11

- El portal de la EBA es de acceso público y los Q&As del Single Rulebook son documentos regulatorios oficiales de la UE.
- La EBA no declara restricciones de uso automatizado en su `robots.txt` para las páginas de Q&As.
- Los contenidos del portal EBA son publicados bajo términos de acceso abierto compatibles con uso institucional no comercial.
- Confirmado: ADR 0011 clasifica EBA Q&As como GREEN con "Datos abiertos EBA".

## Rate limit aplicado

**1 req / 2 s** (`rate_limit_rps = 0.5`), conforme a ADR 0011.

## User-Agent utilizado

```
lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)
```

## Formato de datos esperado

- **Tipo primario:** JSON API (si disponible en endpoints Drupal del portal EBA)
  - Candidatos probados: `/api/v1/single-rulebook-qa`, `/single-rule-book-qa?_format=json`, `/views/single_rulebook_qa?_format=json`
- **Tipo fallback:** HTML scraping del listado
- **Identificador:** `EBA-QA-{número}`, e.g. `EBA-QA-2023001`
- **Campos extraídos:**
  - `topic`: área temática del Q&A
  - `related_articles`: artículos relacionados (CRR, CRD, etc.)
  - `status`: `answered` / `pending` / `unknown`
  - `date_submitted`: fecha de envío de la pregunta
  - `date_answered`: fecha de respuesta
  - `full_text`: texto completo de la página Q&A

## Detección de cambios de formato

| Señal                                               | Causa probable                                                 |
| --------------------------------------------------- | -------------------------------------------------------------- |
| JSON API devuelve error 404/406                     | El portal EBA (Drupal) ha cambiado la arquitectura del backend |
| `list_documents()` devuelve 0 IDs (también en HTML) | La URL o estructura de la página de listado ha cambiado        |
| `status` = `unknown` en >80%                        | Las etiquetas `<dt>` del portal han cambiado de nombre         |
| `topic` vacío en >50%                               | La estructura de metadatos `<dl>` ha sido reemplazada          |

**Nota:** El portal EBA usa Drupal; los endpoints JSON son internos y pueden cambiar con actualizaciones del CMS sin previo aviso.
