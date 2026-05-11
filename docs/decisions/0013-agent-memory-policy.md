# ADR 0013 — Política de memoria del agente

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** ibernale

---

## Context

Los sistemas de agentes con memoria persistente pueden mejorar la calidad de las
respuestas aprovechando interacciones pasadas, patrones observados y hechos estables
sobre el dominio. Frameworks como Letta/MemGPT, Mem0 y Zep ofrecen recuperación
semántica de memoria episódica que permite al agente "recordar" qué se preguntó antes
y adaptar respuestas futuras.

Para lex-agents, operar en el entorno jurídico de un banco sistémico plantea
restricciones específicas que hacen que estas capacidades sean un riesgo antes que
una ventaja en la fase actual.

---

## Decision

Se adoptan **tres tipos de memoria con tres políticas distintas**.

---

### Tipo 1 — Memoria procedimental (workflows aprendidos)

**Estado: ACTIVA**

**Qué almacena:**

- Plantillas de output preferidas por tipo de consulta (dictamen, nota informativa, memo ejecutivo, análisis de riesgo operacional)
- Atajos de routing observados: qué jurisdicciones/ramas correlacionan con qué patrones de consulta
- Patrones de citación preferidos por tipo de norma (reglamento UE vs. ley ES vs. circular BdE)
- Advertencias recurrentes de calidad (e.g., "para consultas sobre CRR III, añadir siempre caveat de régimen transitorio")

**Storage:** SQLite, tabla `procedural_patterns`:

```sql
CREATE TABLE procedural_patterns (
    id          INTEGER PRIMARY KEY,
    pattern_key TEXT NOT NULL UNIQUE,   -- e.g., "output_template:dictamen"
    version     INTEGER NOT NULL DEFAULT 1,
    content     TEXT NOT NULL,          -- JSON o Markdown
    source      TEXT NOT NULL,          -- "human:pr#42" | "human:seed"
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1
);
```

**Quién puede escribir:** exclusivamente humanos vía PR. El agente tiene acceso de
**solo lectura** a esta tabla en runtime. No existe ninguna ruta de código que permita
al agente insertar o modificar filas en runtime.

**Justificación del control humano:** la memoria procedimental influye en el estilo
y estructura de todas las respuestas futuras. Un agente que se auto-modifica su propia
memoria procedimental puede derivar progresivamente hacia patrones no auditados. En
contexto jurídico, un cambio de estilo no auditado puede implicar cambios en el alcance
o la cautela de las respuestas.

---

### Tipo 2 — Memoria semántica (hechos estables del dominio)

**Estado: ACTIVA**

**Qué almacena:**

- Catálogo de jurisdicciones operadas por Santander Group y supervisor competente en cada una
- Marco de supervisores: qué entidad supervisa qué (BdE, CNMV, AEPD, ECB/SSM, FCA, BaFin…)
- Nomenclatura interna del banco: nombres de productos, divisiones, líneas de negocio (no confidencial, nivel policy pública)
- Marcos normativos de referencia por rama: textos de referencia estables que se cargan siempre en el contexto del Planner

**Storage:** YAMLs versionados en `docs/knowledge/`:

```
docs/knowledge/
├── jurisdictions.yaml       # jurisdicciones activas + supervisor
├── supervisors.yaml         # matriz supervisor × rama × jurisdicción
├── bank_nomenclature.yaml   # nombres de productos y divisiones (no confidencial)
└── regulatory_frameworks.yaml  # textos de referencia por rama
```

Los YAMLs se cargan en el contexto del Planner (ADR 0012) al inicio de cada consulta.
No se persisten en SQLite; son código, viven en git.

**Quién puede escribir:** humanos vía PR. Los YAMLs son versionados y auditables en git.

---

### Tipo 3 — Memoria episódica (historial de consultas)

**Estado: DESACTIVADA**

**Qué sería:** recuperación semántica de consultas pasadas para adaptar respuestas
futuras. El agente "recuerda" que el usuario X preguntó sobre la operación Y y usa ese
contexto en consultas posteriores.

**Por qué está desactivada:**

**1. Riesgo de data leakage entre usuarios.** Las consultas jurídicas frecuentemente
contienen información sobre operaciones, clientes o exposiciones no públicas. Si el
sistema recupera semánticamente interacciones pasadas, existe riesgo de que el contexto
de la consulta de un usuario contamine la respuesta a otro usuario con una consulta
semánticamente similar.

**2. Sesgo en consultas similares.** Un agente con memoria episódica tiende a responder
consultas nuevas de forma consistente con cómo respondió consultas pasadas similares,
incluso si el marco normativo ha cambiado. En derecho, la consistencia con el pasado
no es virtud cuando la norma ha evolucionado.

**3. Ausencia de política de retención formal.** El RGPD (Art. 5.1.e) exige que los
datos personales no se conserven más allá de lo necesario. Las consultas jurídicas
pueden contener datos de terceros (clientes del banco, empleados, contrapartes). Sin
una política de retención y base jurídica explícita para el tratamiento, activar
recuperación episódica crea exposición regulatoria.

**4. Responsabilidad profesional.** Si el agente "recuerda" una consulta previa y usa
ese contexto para responder una nueva, está ejerciendo de facto una función de
asesoramiento continuado que requiere validación y supervisión humana explícita para
cada consulta. La arquitectura actual es de consulta discreta e independiente, lo
cual es consistente con el principio de "borrador asistido por IA que requiere
validación".

**Revisión de frameworks existentes:**

| Framework          | Capacidad                                                                         | Por qué no adoptamos (todavía)                                                                                                                               |
| ------------------ | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Letta / MemGPT** | Gestión de memoria en ventana + persistencia episódica con recuperación semántica | La recuperación semántica cross-user es exactamente el riesgo descrito. La gestión en-ventana es útil pero no requiere un framework externo completo         |
| **Mem0**           | Extrae hechos de conversaciones y los persiste para recuperación futura           | La extracción automática de "hechos" de consultas jurídicas crea un grafo de conocimiento no auditado sobre clientes/operaciones. Inaceptable sin gobernanza |
| **Zep**            | Memory store con recuperación semántica, ideal para chatbots de larga duración    | Diseñado para continuidad de conversación; lex-agents opera en consultas discretas. El valor de Zep es bajo y el riesgo de retención no intencionada es alto |

La mayor capacidad que ofrecen estos frameworks —recuperación semántica de interacciones
pasadas— es precisamente lo que no queremos hasta tener gobernanza explícita.

**Sustitución:** las trazas completas de cada consulta (query, response, citations,
verification) se persisten en SQLite (ya implementado, ADR 0007) y son accesibles
por `trace_id`. No hay recuperación semántica cross-consulta. El historial existe
para auditoría y reproducibilidad, no para informar respuestas futuras.

---

## Condición de reevaluación para memoria episódica (Fase 7)

La memoria episódica podrá reevaluarse cuando estén en su lugar **todos**:

1. Política de retención formal aprobada por DPO y Legal del Grupo (plazo máximo de retención, base jurídica, registro de tratamiento)
2. Aislamiento de memoria por usuario/sesión con controles de acceso auditables
3. Mecanismo de borrado efectivo (derecho de supresión RGPD Art. 17)
4. Revisión de seguridad por Riesgos Operacionales del modelo de recuperación semántica
5. Prueba de concepto limitada en entorno sandbox con datos sintéticos, no con consultas reales

---

## Consequences

**Positivo:**

- La memoria procedimental y semántica aportan consistencia y contexto sin riesgo
- La desactivación de episódica elimina la mayor fuente de riesgo regulatorio de los sistemas de agentes con memoria
- El control humano estricto sobre escritura de memoria crea un audit trail limpio

**Negativo/Riesgos:**

- El agente no "aprende" de interacciones pasadas; cada consulta parte del mismo estado base. Para mejorar calidad se requiere intervención humana explícita (actualizar YAMLs o `procedural_patterns`)
- Los patrones de preferencia del usuario individual no se capturan; la personalización está limitada a la memoria semántica institucional

**Neutral:**

- La decisión de no adoptar Letta/MemGPT/Mem0/Zep ahora no cierra la puerta a adoptarlos en Fase 7 bajo las condiciones establecidas; simplifica la arquitectura en esta fase
