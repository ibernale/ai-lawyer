# Fuente: ESMA Q&As

## URL base

```
https://www.esma.europa.eu/publications-and-data/questions-and-answers
```

## Términos de uso consultados

**Fecha de consulta:** 2026-05-11

- El portal de ESMA es de acceso público; los Q&As son documentos regulatorios oficiales de la UE.
- ESMA no declara restricciones de acceso automatizado en `robots.txt` para páginas de publicaciones.
- Contenidos publicados bajo términos de acceso abierto de una agencia de la UE.
- ADR 0011 clasifica ESMA Q&As como GREEN ("Publicación oficial ESMA").

## Rate limit aplicado

**1 req / 2 s** (`rate_limit_rps = 0.5`), conforme a ADR 0011.

## User-Agent utilizado

```
lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)
```

## Formato de datos esperado

- **Tipo:** HTML scraping con paginación (`?page=N`)
- **No existe API JSON pública** detectada a 2026-05-11
- **Identificador:** `ESMA-QA-{ref}` donde `ref` es el número de referencia ESMA (e.g. `70-1861941480-52`) o el slug de URL
- **Campos extraídos:**
  - `qa_id`: número de referencia ESMA
  - `topic`: área temática
  - `regulation_reference`: regulación o directiva de referencia
  - `publication_date`: fecha de publicación (del elemento `<time>`)
  - `full_text`: texto completo de la página

## Detección de cambios de formato

| Señal | Causa probable |
|-------|----------------|
| `list_documents()` devuelve 0 IDs | La URL del listado ha cambiado o la paginación ya no usa `?page=N` |
| `qa_id` vacío en >60% | El formato de referencia ESMA ha cambiado o los `<dt>` ya no los contienen |
| `regulation_reference` vacío sistemáticamente | La estructura `<dl>` de metadatos ha sido eliminada |
| Pocas páginas scrapeadas (< 5) cuando se esperan más | El portal ESMA ha implementado infinite scroll o protección anti-bot |

**Nota:** El portal ESMA está parcialmente migrado a nuevo CMS; la estructura HTML puede cambiar sin previo aviso.
