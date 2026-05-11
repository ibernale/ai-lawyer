# Fuente: BdE Circulares

## URL base

```
https://www.bde.es/wbe/es/normativa/circulares-otra-normativa/
```

## Términos de uso consultados

**Fecha de consulta:** 2026-05-11

- El Banco de España publica sus circulares como normativa oficial bajo el régimen de publicación pública del Banco de España.
- Las circulares son de acceso libre y descarga gratuita.
- El sitio web del BdE no declara restricciones de scraping automatizado en su `robots.txt` para páginas normativas (consultado 2026-05-11).
- Uso interno no comercial compatible con la política de datos abiertos del BdE.

## Rate limit aplicado

**1 req / 2 s** (`rate_limit_rps = 0.5`), conforme a ADR 0011.

## User-Agent utilizado

```
lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)
```

## Formato de datos esperado

- **Tipo primario:** RSS XML (si disponible en el endpoint `/rss.xml` o `/wbe/rss/normativa/circulares.xml`)
- **Tipo fallback:** HTML scraping del listado
- **Identificador:** `BDE-CIRC-{número}-{año}`, e.g. `BDE-CIRC-9-2010`
- **Campos extraídos:**
  - `circular_number`: número de la circular (e.g. `9`)
  - `year`: año (e.g. `2010`)
  - `subject`: primer párrafo descriptivo de la página
  - `normas_modificadas`: texto extraído por regex que mencione modificaciones/derogaciones
  - `full_text`: texto completo de la página

## Detección de cambios de formato

| Señal | Causa probable |
|-------|----------------|
| `_try_rss()` devuelve 0 items pero la fuente era funcional | El BdE ha eliminado o movido el endpoint RSS |
| `_list_from_html()` devuelve 0 items | La URL del listado HTML o la estructura de links ha cambiado |
| `circular_number` vacío en >30% | El patrón regex `Circular \d+/\d{4}` ya no coincide con los títulos del BdE |
| `normas_modificadas` vacío sistemáticamente | El patrón de texto ha cambiado (poco probable, texto jurídico estable) |

**Nota:** El BdE no confirma la existencia de un RSS público para circulares normativas; se intentan dos candidatos de URL antes de caer al HTML.
