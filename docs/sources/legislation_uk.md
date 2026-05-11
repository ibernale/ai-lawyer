# Fuente: legislation.gov.uk

## URL base

```
https://www.legislation.gov.uk/developer/formats/xml
```

Endpoint XML por documento:

```
https://www.legislation.gov.uk/{type}/{year}/{number}/data.xml
```

## Cobertura inicial

| Doc ID         | Path            | Descripción                             |
| -------------- | --------------- | --------------------------------------- |
| `FSMA-2000`    | `ukpga/2000/8`  | Financial Services and Markets Act 2000 |
| `BOE-ACT-1998` | `ukpga/1998/11` | Bank of England Act 1998                |

Para ampliar la cobertura, añadir entradas a `INITIAL_CORPUS` en `legislation_uk.py`.

## Términos de uso consultados

**Fecha de consulta:** 2026-05-11

- legislation.gov.uk publica bajo **Open Government Licence v3.0 (OGL v3)**.
- OGL v3 permite uso, adaptación, reproducción y distribución con atribución.
- La API XML oficial está documentada en `https://www.legislation.gov.uk/developer`.
- Uso no comercial e institucional explícitamente permitido.
- No se requiere registro ni API key.

## Rate limit aplicado

**1 req / 1 s** (`rate_limit_rps = 1.0`), conforme al uso razonable de la API pública.

## User-Agent utilizado

```
lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)
```

## Formato de datos esperado

- **Tipo:** XML (AKN — Akoma Ntoso / formato propietario legislation.gov.uk)
- **Namespaces principales:** `http://www.legislation.gov.uk/namespaces/legislation`, `http://purl.org/dc/elements/1.1/`
- **Estructura esperada:** `Part` → `Chapter` → `Section` con `Heading` y párrafos

## Detección de cambios de formato

| Señal                                       | Causa probable                                                   |
| ------------------------------------------- | ---------------------------------------------------------------- |
| `etree.XMLSyntaxError` en parse             | El endpoint ha dejado de devolver XML válido (poco probable)     |
| `title` vacío                               | El tag de título (`Title`, `LongTitle`, `dc:title`) ha cambiado  |
| `hierarchy` vacío pero `full_text` no vacío | Los tags `Part`/`Section` han sido renombrados en el esquema     |
| HTTP 404                                    | La legislación ha sido retirada del portal o el path ha cambiado |
| HTTP 301/302 a HTML                         | El endpoint XML ya no está disponible para ese documento         |

**Contacto API:** `https://www.legislation.gov.uk/developer/contact`
