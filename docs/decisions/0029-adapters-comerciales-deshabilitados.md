---
adr: "0029"
title: "Adapters comerciales preparados pero deshabilitados"
date: 2026-05-11
status: accepted
deciders: [ibernale]
phase: "7.0"
---

# ADR 0029 — Adapters comerciales preparados pero deshabilitados

## Contexto

Las fuentes comerciales de jurisprudencia y doctrina (Aranzadi/Thomson Reuters,
Tirant lo Blanch, La Ley/Wolters Kluwer) ofrecen cobertura de calidad superior
a las fuentes públicas gratuitas, pero requieren:

1. Licencia de uso que autorice explícitamente el procesamiento mediante LLM/RAG.
2. Proceso interno de aprobación en Grupo Santander (Legal + Procurement + IT).
3. Presupuesto aprobado.

El estado actual de negociaciones se documenta en `docs/legal/comerciales-status.md`.

El objetivo de este ADR es permitir que el equipo de ingeniería implemente los
adapters técnicos ahora — mientras las licencias se tramitan — sin riesgo de
uso accidental o inadvertido antes de la autorización.

## Decisión

### 1. Patrón de implementación

Las clases `Source` para fuentes comerciales se implementan completas
(métodos `fetch`, `parse`, `embed` con lógica real) pero con una guarda
al inicio de cada método que accede a red o datos reales:

```python
class AranzadiSource(BaseSource):
    def fetch(self, query: str) -> list[RawDocument]:
        _require_license("aranzadi")   # raises si no autorizado
        ...

def _require_license(source_name: str) -> None:
    if not settings.commercial_sources.get(source_name, {}).get("enabled", False):
        raise CommercialSourceDisabledError(
            f"Source '{source_name}' is disabled. "
            f"Set CONFIG_LICENSE_VERIFIED=true and enable in settings to activate."
        )
```

`CommercialSourceDisabledError` hereda de `Exception`, no de `ValueError`.
Es un error conocido y esperado — no debe producir alert en producción cuando
la fuente está configurada como deshabilitada.

### 2. Modo test con fixtures

El constructor de cada adapter acepta `fixture_path: Path | None = None`.
Cuando se proporciona, los métodos de red leen del directorio de fixtures
y **no ejecutan `_require_license`** (es un entorno de test, no activación
de la fuente real):

```python
def fetch(self, query: str) -> list[RawDocument]:
    if self._fixture_path is not None:
        return self._load_fixtures(query)
    _require_license(self._source_name)
    ...
```

Los fixtures de test se almacenan en
`packages/ingest/tests/fixtures/comerciales/{source_name}/`.
Los tests CI usan exclusivamente fixtures; nunca tocan red ni requieren licencia.

### 3. Toggle de activación

La activación de una fuente comercial requiere dos condiciones simultáneas:

1. **Variable de entorno**: `CONFIG_LICENSE_VERIFIED=true` presente en el
   entorno de ejecución.
2. **Configuración explícita**: el source específico marcado como `enabled: true`
   en la configuración (`settings.commercial_sources.aranzadi.enabled = true`).

Si `CONFIG_LICENSE_VERIFIED` no está definida o es `false`, ningún source
comercial puede activarse, independientemente de la configuración.

Esta doble barrera evita activaciones accidentales por despliegue de una
configuración incorrecta.

### 4. Validación en startup

Al arrancar la API (`lifespan` de FastAPI), se ejecuta una validación:

```python
for source_name, source_config in settings.commercial_sources.items():
    if source_config.enabled and not settings.license_verified:
        raise StartupError(
            f"Commercial source '{source_name}' is enabled in config but "
            f"CONFIG_LICENSE_VERIFIED is not set. "
            f"Verify the license before enabling commercial sources."
        )
```

El error en startup es preferible al error en runtime porque:
- Es inmediatamente visible en los logs de despliegue.
- No permite que el sistema arranque en un estado inconsistente.
- El operador puede corregirlo antes de que llegue tráfico real.

### 5. Referencia a docs/legal/comerciales-status.md

El ADR no duplica la tabla de editoriales. El estado actualizado de licencias,
costes y contactos está en `docs/legal/comerciales-status.md`. Ese fichero
es la fuente canónica.

### 6. Fuentes candidatas para fase 8

Las siguientes fuentes están identificadas como candidatas; su implementación
técnica puede comenzar en fase 7 siguiendo este patrón, pero ninguna puede
activarse hasta completar el proceso de licencia:

| Editorial | Producto | Tipo de licencia recomendado | Gate |
| --------- | -------- | ---------------------------- | ---- |
| Aranzadi / Thomson Reuters | Insignis | API + permiso uso LLM explícito | Procurement Santander |
| Tirant lo Blanch | Tirant Online | Licencia institucional + cláusula RAG | Procurement Santander |
| La Ley / Wolters Kluwer | La Ley Digital | API jurisprudencia + permiso scraping | Procurement Santander |

Para cada fuente, el equipo legal de Santander debe confirmar que los términos
de la licencia permiten:
- Indexación mediante embeddings.
- Recuperación de fragmentos para contexto LLM.
- Almacenamiento temporal de fragmentos en Qdrant (no redistribución).

## Alternativas consideradas

**No implementar hasta tener licencia** — rechazado. El lead time de
negociaciones es 3–6 meses. Implementar ahora reduce el tiempo desde
licencia-aprobada hasta disponible-en-producción a días.

**Feature flag en config sin variable de entorno** — rechazado. Una config
en fichero puede desplegarse accidentalmente. La variable de entorno es
una barrera adicional que requiere intervención manual explícita en el
entorno de producción.

**Stub vacío (raise NotImplementedError)** — rechazado. Un stub vacío no
aporta valor de test ni permite validar el schema de integración. Las clases
completas con fixtures permiten verificar que el pipeline funciona
end-to-end antes de tener la licencia.

## Consecuencias

- Nuevo módulo `packages/ingest/src/.../sources/comerciales/` con clases
  `AranzadiSource`, `TirantSource`, `LaLeySource` (estructura, no activado).
- Nueva excepción `CommercialSourceDisabledError` en `packages/shared`.
- Validación de startup en `apps/api/src/.../main.py`.
- Fixtures de test en `packages/ingest/tests/fixtures/comerciales/`.
- `docs/legal/comerciales-status.md` actualizado para reflejar este ADR.
- `CONFIG_LICENSE_VERIFIED` documentada en `.env.example` con valor `false`
  por defecto y comentario explicativo.
