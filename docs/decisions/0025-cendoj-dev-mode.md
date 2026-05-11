---
adr: "0025"
title: "Política CENDOJ dev mode"
date: 2026-05-11
status: accepted
deciders: [ibernale]
phase: "7.0"
---

# ADR 0025 — Política CENDOJ dev mode

## Contexto

CENDOJ (Centro de Documentación Judicial del CGPJ) expone jurisprudencia
española a través de su portal público. No existe una API REST oficial
documentada para uso programático masivo; el acceso masivo sin autorización
viola los términos de servicio y compromete la relación institucional con el
CGPJ. Referencia: `docs/legal/cendoj-status.md`.

La fase 7.1 integra CENDOJ en modo desarrollo (local-only, scraping
controlado con rate limiting duro) como puente hasta obtener una autorización
formal. Los principios que guían este ADR son:

1. **Evidencia de buena fe**: cada decisión técnica debe poder presentarse
   ante el CGPJ como demostración de uso responsable.
2. **Fail-fast sobre fail-silent**: si el sistema no puede operar dentro del
   límite, debe parar ruidosamente, no degradarse en silencio.
3. **Reversibilidad**: el modo dev puede desactivarse con un flag sin tocar
   código de negocio.

## Decisión

### 1. Rate limit duro

- **Límite**: 50 requests/día al dominio `cendoj.poderjudicial.es`.
- **Contador**: SQLite en `data/cendoj_quota.db`, tabla `quota_log` con
  columnas `(date TEXT, count INTEGER)`. Un solo registro por día UTC.
- **Reset**: automático a 00:00 UTC. Si el fichero no existe al arrancar,
  se crea con `count = 0`.
- **Atomicidad**: el contador se actualiza dentro de una transacción SQLite
  `BEGIN IMMEDIATE` para evitar race conditions si hay workers paralelos.

### 2. Comportamiento en escasez de cuota

| Cuota restante | Comportamiento |
| -------------- | -------------- |
| ≥ 10           | Normal         |
| 1–9            | Backoff de 60 s entre requests; log `WARNING quota_low` con remaining |
| 0              | `CendojQuotaExhaustedError` inmediato; ningún request adicional ese día |

`CendojQuotaExhaustedError` es un error conocido: el orquestador lo captura,
excluye CENDOJ de las fuentes de esa consulta y añade al response la nota:
"Fuente jurisprudencial CENDOJ no disponible hoy (cuota dev agotada). Los
resultados se basan en fuentes normativas."

### 3. Comportamiento ante errores HTTP del servidor

| Código recibido    | Acción                                                                   |
| ------------------ | ------------------------------------------------------------------------ |
| 429 Too Many Requests | Detención inmediata. Flag `CENDOJ_SUSPENDED=true` en `cendoj_quota.db`. No reintentar hasta intervención humana. |
| 403 Forbidden      | Ídem.                                                                    |
| Captcha detectado  | Ídem (detección por `<title>` o body pattern).                           |
| 5xx servidor       | Reintento con backoff exponencial máx. 3 veces; si persiste, excluir fuente (no suspender). |

El flag `CENDOJ_SUSPENDED` se comprueba al arrancar el asset Dagster. Si está
activo, el asset falla con mensaje claro que requiere intervención manual para
resetear.

**Justificación del no-reintento**: un 429/403 indica que el servidor ha
detectado el acceso. Reintentar automáticamente agravaría la situación y
eliminaría la evidencia de buena fe. El log estructurado (`structlog`) con
timestamp, URL y código es la evidencia que se presentará ante el CGPJ si
fuera necesario.

### 4. Headers de identificación

Todas las requests del scraper CENDOJ incluyen:

```
User-Agent: lex-agents-dev/0.3 (banking-compliance-research; contact: <CONTACT_EMAIL>)
X-Purpose: internal-research-dev
```

`CONTACT_EMAIL` se toma de la variable de entorno `CENDOJ_CONTACT_EMAIL`.
Si no está definida, el scraper no arranca (error en startup, no en runtime).

### 5. Aviso obligatorio en respuestas con cita CENDOJ

Cada respuesta que contenga al menos una `CitationMapping` con
`source_type = "cendoj"` debe incluir al final del campo `answer` el
siguiente párrafo (añadido automáticamente por el especialista o el
orquestador, no por el LLM):

> *Recuperado en modo desarrollo CENDOJ (rate-limited). El uso productivo
> de jurisprudencia CENDOJ requiere autorización formal del CGPJ, pendiente
> de solicitud en fase 8.*

El aviso también aparece en logs con nivel `INFO` y en el span de trazabilidad
(`cendoj_dev_mode = true`).

### 6. Modo test / fixtures

Para que los tests de integración no consuman cuota real:

- El constructor de `CendojSource` acepta `fixture_path: Path | None = None`.
- Si `fixture_path` no es `None`, las llamadas a `fetch()` leen del directorio
  de fixtures local en lugar de hacer HTTP. El quota counter **no se
  incrementa** en modo fixture.
- Los fixtures de test se almacenan en
  `packages/ingest/tests/fixtures/cendoj/`.

### 7. Solicitud formal CGPJ (fuera de alcance fase 7)

La autorización formal del CGPJ para uso programático de CENDOJ NO se
inicia en la fase 7. Cuando se decida iniciar (previsiblemente fase 8),
los pasos son:

1. Redactar memoria técnica con propósito, volumen estimado, medidas de
   seguridad y contacto institucional.
2. Presentar a través del formulario oficial CGPJ o correo institucional
   del Centro de Documentación Judicial.
3. Esperar resolución (plazo habitual: 4–8 semanas).
4. Si autorizado: eliminar rate limit duro, mantener headers de
   identificación, actualizar `docs/legal/cendoj-status.md`.
5. Si denegado: detener scraping CENDOJ, evaluar alternativas (INLABS,
   API Jurisprudencia TC, fuentes privadas).

## Alternativas consideradas

**Rate limit más alto (200 req/día)** — rechazado. Sin autorización formal,
cualquier límite es arbitrario; 50 req/día es suficiente para dev y
demuestra restricción voluntaria.

**Sin rate limit en dev local** — rechazado. El entorno local puede conectarse
a red corporativa; un dev descuidado podría consumir miles de requests. El
límite en SQLite es trivial de implementar y elimina el riesgo.

**Cache de HTML crudo en disco** — aceptable como optimización futura, no
en este ADR. La preocupación de privacidad (sentencias con datos personales
no anonimizados) requiere un ADR separado antes de persistir HTML.

## Consecuencias

- Nuevo módulo `packages/ingest/src/.../cendoj.py` con `CendojSource`,
  `CendojQuotaStore` y `CendojQuotaExhaustedError`.
- Nueva base de datos `data/cendoj_quota.db` (gitignored).
- Variable de entorno `CENDOJ_CONTACT_EMAIL` requerida cuando CENDOJ está
  habilitado.
- Los tests de CENDOJ usan siempre fixtures; nunca tocan red en CI.
- Ver ADR 0024 para las reglas de verificación estricta que aplican a las
  citas extraídas de CENDOJ.
