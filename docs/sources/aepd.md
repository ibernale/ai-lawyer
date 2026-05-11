# Fuente: AEPD Resoluciones

## URL base

```
https://www.aepd.es/es/resoluciones-y-actuaciones/resoluciones
```

Página individual de resolución:

```
https://www.aepd.es/es/documento/PS-XXXXX-YYYY
```

## Términos de uso consultados

**Fecha de consulta:** 2026-05-11

- La AEPD publica sus resoluciones bajo el régimen de publicación oficial (Ley 19/2013 de transparencia).
- Los datos publicados son de carácter público y de acceso libre.
- No existe prohibición expresa de descarga automatizada para uso interno no comercial.
- El buscador público no declara explícitamente restricciones de scraping en su `robots.txt` (consultado 2026-05-11).
- Uso interno Santander cubierto por el principio de acceso a información pública.
- **Acción pendiente:** confirmar interpretación con Legal del Grupo antes de activar ingestión masiva.

## Rate limit aplicado

**1 req / 3 s** (`rate_limit_rps = 1/3`), conforme a la recomendación de ADR 0011 para fuentes de scraping HTML.

## User-Agent utilizado

```
lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)
```

## Formato de datos esperado

- **Tipo:** HTML (no existe API XML/JSON pública)
- **Identificador:** Número de procedimiento, formato `PS/XXXXX/YYYY` (e.g. `PS/00001/2024`)
- **Campos extraídos:**
  - `title`: título de la resolución (del `<h1>`)
  - `publication_date`: fecha de la resolución (elemento `<time>`)
  - `resolution_type`: tipo inferido del texto (`sancionadora`, `tutela`, `informe`)
  - `sanction_amount_eur`: importe de la sanción si aparece en el texto
  - `full_text`: texto completo extraído del `<article>` o `<main>`

## Detección de cambios de formato

El parser fallará o devolverá datos vacíos en los siguientes casos:

| Señal                                             | Causa probable                                                                 |
| ------------------------------------------------- | ------------------------------------------------------------------------------ |
| `title` vacío en >20% de documentos               | La AEPD ha cambiado la estructura del `<h1>` o añadido JavaScript rendering    |
| `publication_date` = `date.today()` en >50%       | El elemento `<time>` ha sido eliminado o renombrado                            |
| `sanction_amount_eur` ausente cuando se esperaría | El patrón regex (`multa de X euros`) ha cambiado en el texto                   |
| `list_documents()` devuelve 0 IDs                 | La URL de la página de resultados ha cambiado o el patrón de links ha cambiado |

**Acción recomendada ante fallos:** ejecutar `make eval-quick` con el conjunto de resoluciones de prueba y revisar métricas de campos vacíos.
