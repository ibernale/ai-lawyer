# ADR 0021 — Política de Prompt Evolution Semi-Automático

**Estado:** Aceptado  
**Fecha:** 2026-05-11  
**Autores:** equipo lex-agents  
**Supersede:** ADR 0015 (sustituido por este ADR con implementación concreta)  
**Relacionados:** ADR 0020 (LeMAJ), ADR 0014 (política LeMAJ)

---

## Contexto

El sistema LeMAJ (ADR 0020) identifica casos donde los prompts de los especialistas producen LDPs no soportados o cobertura de conceptos insuficiente. Este ADR define el proceso gobernado para proponer, validar y revisar mejoras de prompts derivadas de esos análisis.

El riesgo principal que este ADR mitiga: **una IA proponiendo y fusionando cambios en prompts jurídicos sin revisión humana**. Dado que los prompts determinan el tono, alcance y cautelas de las respuestas legales del sistema, cualquier cambio no revisado podría introducir omisiones de cautelas, expansión de alcance o interpretaciones incorrectas.

---

## Decisión

### Alcance: solo prompts de especialistas (Fase 1)

Los únicos prompts elegibles para evolución automática son los de especialistas:
```
docs/prompts/especialistas/<branch>/v<N>.md
```

Los siguientes están **protegidos** y excluidos en la Fase 1:
- `docs/prompts/router/**`
- `docs/prompts/planner/**`
- `docs/prompts/judge/**`
- `docs/prompts/lemaj/**`

La protección del router y planner se debe a que sus cambios tienen impacto de sistema. La protección de los prompts de jueces y LeMAJ evita circularidad (el sistema que evalúa no puede auto-modificar sus propios criterios de evaluación sin revisión humana).

### Pipeline: cuatro etapas

```
FailureAnalyzer → PromptProposer → RegressionSim → PROpener
```

#### Etapa 1: FailureAnalyzer

Criterios de fallo por caso:
- `ldp_unsupported_rate > 0.15` (más del 15% de LDPs no soportados), O
- `concept_coverage < 0.60` (menos del 60% de conceptos esperados cubiertos).

Los casos fallidos se agrupan por `branch_expected`. Solo los clusters con ≥1 caso fallido generan una propuesta.

#### Etapa 2: PromptProposer

Para cada cluster, llama a claude-opus-4-7 con:
- El prompt actual del especialista.
- Hasta 3 casos fallidos con sus LDPs no soportados y razonamiento de los jueces.
- Instrucciones explícitas de generar un diff unificado conservador.

El prompt del proposer incluye explícitamente: *"No amplíes el alcance del especialista, mantén todas las cautelas, sé conservador".*

Output: diff en formato unificado (`--- a/... +++ b/...`) + rationale.

Validación automática de ADR compliance: si el rationale contiene `⚠️` o la palabra "expand", el diff se marca `adr_compliant=False`. Los diffs no conformes no generan PR (se registran en log).

#### Etapa 3: RegressionSim

Para cada diff propuesto:
1. Aplica el diff **en memoria** (no a disco) con `patch --output=-`.
2. Carga hasta 5 casos "vecinos" del golden_dataset para la misma rama (selección por orden de archivo; selección por similitud embeddings prevista para Fase 6.4).
3. Evalúa heurísticamente cada caso con el prompt candidato: cobertura de conceptos esperados + tasa de claims prohibidos.
4. Acepta el diff si y solo si **ningún caso vecino regresa** (cobertura no cae más de 10 puntos porcentuales y tasa de claims prohibidos = 0).

Si no hay casos vecinos disponibles: el diff se acepta por defecto (con nota en el log). Si la aplicación del diff falla: el diff se rechaza.

#### Etapa 4: PROpener

Para cada diff aceptado por RegressionSim:
1. Crea rama `prompt-evolution/<timestamp>-<branch>`.
2. Aplica el diff al archivo de prompt en disco.
3. Incrementa versión MINOR en el frontmatter YAML del prompt (`version: N` → `version: N+1`).
4. `git add`, `git commit` (co-authored por reflection agent), `git push`.
5. `gh pr create` con labels `prompt-evolution` y `needs-human-review`.

**INVARIANT ABSOLUTO**: El módulo `pr_opener.py` nunca llama `gh pr merge`. Este invariant está comentado explícitamente en el código y verificado por un test automatizado (`test_reflection.py::TestPROpenerInvariant`).

### Gobernanza: revisión humana obligatoria

El archivo `.github/CODEOWNERS` asigna `@ibernale` como revisor requerido de todos los prompts de especialistas:
```
docs/prompts/especialistas/**  @ibernale
```

GitHub impide el merge de cualquier PR que modifique rutas bajo `docs/prompts/especialistas/` sin al menos una aprobación de `@ibernale`. Esto garantiza que ningún cambio pueda fusionarse sin revisión humana, incluso si alguien obtiene permisos de escritura en el repositorio.

El checklist de cada PR incluye:
- Revisión por jurista del impacto en tono y alcance.
- Verificación de que las cautelas legales obligatorias se mantienen.
- Compatibilidad con ADRs 0010–0021.

### Versionado de prompts

- **MINOR** (N+1): clarificaciones, ejemplos adicionales, reformulaciones sin cambio de alcance. Generado automáticamente por este pipeline.
- **MAJOR** (nuevo archivo `v<M>.md`): cambios de alcance, nuevas cautelas, cambios de formato estructural. Requiere proceso manual y ADR o nota de cambio.

Auditoría cada 10 versiones MINOR: un jurista revisa el delta acumulado para detectar deriva semántica no prevista.

### Modo dry-run

El comando:
```
python -m lex_agents_evals_advanced.reflection run \
  --results-dir evals/reports/<run_id>/ \
  --dry-run
```
ejecuta todo el pipeline pero omite las llamadas a git y gh. Imprime los diffs propuestos y el resultado de la simulación de regresión. Útil para depuración y auditoría manual.

---

## Consecuencias

- **Positivas:** Ciclo de mejora continua con mínima fricción; los cambios propuestos son siempre revisables antes de merge; el sistema no puede auto-mergearse.
- **Negativas:** La simulación de regresión es heurística (no ejecuta el LLM real con el prompt candidato); hay riesgo de falsos positivos (diffs aceptados que degradan calidad real). Esto se mitiga con la revisión humana obligatoria.
- **Neutras:** Los diffs rechazados por regresión se registran en log para análisis posterior. Si el pipeline propone diffs con frecuencia pero todos son rechazados, indica que los thresholds de FailureAnalyzer o RegressionSim necesitan recalibración.

---

## Notas de implementación

- `packages/evals_advanced/src/lex_agents_evals_advanced/reflection/` contiene los 4 módulos.
- Test de invariant en `packages/evals_advanced/tests/test_reflection.py::TestPROpenerInvariant::test_no_gh_pr_merge_subprocess_call`.
- El pipeline nightly se define en `.github/workflows/lemaj-nightly.yml` y se ejecuta a las 03:00 UTC.
