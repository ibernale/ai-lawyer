# Demo guide — lex-agents v0.2.0

Guion para demostración de 20 minutos. Audiencia: dirección jurídica y cumplimiento.

---

## Preparación (antes de la demo)

```bash
make dev-detached           # arranca todos los servicios en background
make ingest-sample          # indexa fixtures (necesario si Qdrant está vacío)
curl http://localhost:8000/health  # verificar: status=healthy
open http://localhost:3000  # abrir interfaz web
```

Obtener token de acceso:

```bash
curl -X POST http://localhost:8000/auth/token \
  -d "username=demo&password=demo1234" \
  -H "Content-Type: application/x-www-form-urlencoded"
# → {"access_token":"<token>","token_type":"bearer","expires_in":28800}
```

---

## Query 1 — Fácil: ratio CET1 (2 min)

**Objetivo:** mostrar cita verificada + chip [REF:n] clicable.

En la interfaz web, tipo documento **Dictamen**, consulta:

> ¿Cuál es el requisito mínimo de capital CET1 que establece el Reglamento (UE) 575/2013 para las entidades de crédito?

**Puntos a destacar:**

- El chip `[1]` aparece inline en el texto — clic → panel lateral muestra fragmento exacto del CRR, artículo 92, jerarquía normativa, enlace a EUR-Lex.
- Banner de verificación verde: "Citas verificadas" con ratio claims_passed/claims_total.
- Sin cita inventada: si el modelo no encuentra respaldo normativo, lo declara explícitamente.

**Metadatos técnicos** (clic en "Metadatos técnicos"):

- Latencia típica: 4–8 s
- Coste estimado: ~$0.01

---

## Query 2 — Media: MREL + transposición ES (4 min)

**Objetivo:** mostrar razonamiento multi-norma (BRRD + Ley 11/2015).

Tipo documento **Nota informativa**, consulta:

> Explique los requisitos MREL aplicables a las entidades de resolución españolas: base legal europea, transposición en España y diferencias con los requisitos de Basilea III en materia de absorción de pérdidas.

**Puntos a destacar:**

- Múltiples chips [REF:1], [REF:2], [REF:3] — cada uno resuelve a una norma distinta (BRRD, Ley 11/2015, Circular BdE).
- Banner amarillo si alguna afirmación tiene confianza media: "Verificación parcial — revisar lagunas".
- Sección "Lagunas declaradas": el modelo admite qué no puede verificar con los chunks disponibles (honestidad sobre cobertura del dataset).
- Botón **Exportar Word** → descarga `.docx` con disclaimer en cabecera y pie, listo para revisión del jurista.

---

## Query 3 — Fuera de alcance: expediente de regulación de empleo (2 min)

**Objetivo:** mostrar el guardrail de scope.

Tipo documento **Dictamen**, consulta:

> ¿Cuál es el procedimiento para tramitar un expediente de regulación de empleo (ERE) en una empresa de más de 50 trabajadores?

**Puntos a destacar:**

- El sistema enruta a `fuera_de_alcance` (sin cita normativa bancaria).
- Respuesta explica qué cubre el sistema (regulación bancaria UE+ES) y qué no.
- No alucina normas laborales: banner rojo nunca debería aparecer para este caso; la respuesta es un rechazo limpio.

---

## Cierre: flujo de feedback (1 min)

En cualquier respuesta:

1. Clic en **Reportar problema** → formulario con tipo (Error factual / Cita incorrecta / Fuera de alcance / Otro) + descripción libre.
2. Enviar → confirmación "Feedback guardado (Trace: xxxxxxxx)".
3. El fichero se escribe en `evals/feedback/` — base para fine-tuning futuro.

---

---

## Bloque 2 — Consulta profunda multi-jurisdicción (5 min)

**Objetivo:** mostrar el stack PMJ completo (Planner + Maker + Judge) y la vista cross-jurisdicción.

Tipo documento **Dictamen**, profundidad **Profundo**, jurisdicciones seleccionadas: **ES, EU, UK, BR**.

Consulta:

> Un banco español filial de Santander quiere implantar un modelo de scoring crediticio basado en machine learning que usa datos biométricos para clientes en España, Reino Unido y Brasil. ¿Qué debemos analizar?

**Puntos a destacar:**

- Banner de detección: "Ramas detectadas automáticamente: `regulatorio_bancario`, `datos_personales_rgpd`" + jurisdicciones ES, EU, UK, BR.
- Panel "Razonamiento del sistema" → muestra ramas, pesos, DoD (Planner), scores del Judge por dimensión.
- Collapsibles por rama: "Respuestas por rama especializada" → expandir `datos_personales_rgpd` para mostrar el análisis RGPD específico.
- Judge: si detecta brecha "AI Act aplicabilidad", la muestra en "Brechas identificadas"; el sistema itera una vez.
- UK: la rama incluye nota de cobertura limitada (FCA/PRA sources, no CENDOJ).
- BR: la rama incluye aviso "asesoría local requerida" — no hay fuentes BACEN indexadas en v0.2.0.
- Caveat obligatorio en la respuesta final: "Borrador asistido por IA, requiere validación jurista".

**Metadatos técnicos:**

- Latencia típica: 45–70 s (deep path, 2 ramas, 1 iteración Judge)
- Coste estimado: ~$0.40–0.60

---

## Bloque 3 — Memoria estratificada (4 min)

**Objetivo:** mostrar cómo la memoria procedimental y semántica condiciona el análisis.

Abrir Jaeger (`http://localhost:16686`) → buscar trace de la consulta anterior.

**Puntos a destacar:**

- Span `planner.plan` → atributo `memory.injected=true`.
- Atributo `memory.semantic_snippets` muestra qué fragmentos de `docs/knowledge/` se inyectaron.
- Atributo `memory.procedural_patterns` muestra si el patrón CRR-transitional se activó.
- Explicar: la memoria semántica aporta definiciones de 11 jurisdicciones + 16 frameworks sin ocupar tokens de RAG; la procedimental aporta pasos y precondiciones del análisis CRR.

---

## Bloque 4 — LeMAJ y pipeline adversarial (3 min)

**Objetivo:** mostrar la capa de calidad offline.

```bash
# Dry-run LeMAJ sobre los últimos 5 dictámenes guardados
uv run python -m lex_agents_evals_advanced.lemaj run --dry-run --last 5

# Mostrar salida: LDP rates, Kappa inter-juez, review_required cases
```

**Puntos a destacar:**

- LeMAJ: 5 jueces independientes (Factual / Normativa / Jurisdiccional / Completud / Cautelas) + MetaJudge de consenso.
- Kappa Cohen: si < 0.6, el sistema marca `review_required=True` y registra en Grafana.
- Reflection pipeline: cuando un caso falla, `FailureAnalyzer` → `PromptProposer` (propone diff) → `RegressionSim` → `PROpener` abre PR automáticamente. **Nunca hace merge automático** (ADR 0021).

```bash
# Adversarial suite dry-run
uv run python -m lex_agents_evals_advanced.adversarial run \
  --dataset evals/adversarial_dataset/ --dry-run
```

- 180 casos: 6 niveles × 30 pares (jailbreak, prompt injection, scope bypass, etc.).
- Umbral CI: jailbreak_acceptance_rate = 0.0 (zero tolerance).

---

## Bloque 5 — Grafana (2 min)

Abrir `http://localhost:3001` → dashboard "lex-agents".

**Paneles a mostrar:**

- Depth distribution: ver qué % de consultas son deep vs. standard vs. shallow.
- Branch distribution: ramas más consultadas.
- Cost per branch: coste acumulado por especialista.
- Adversarial panel: confirmar jailbreak_acceptance_rate = 0 (verde).

Cambiar a dashboard "LeMAJ":

- LDP supported/unsupported rates por rama.
- Kappa inter-juez tendencia.

---

## Bloque 6 — Prompt evolution PR + roadmap (1 min)

```bash
# Simular apertura de PR de mejora de prompt (dry-run)
uv run python -m lex_agents_evals_advanced.reflection run \
  --specialist datos_personales_rgpd --dry-run
```

- Muestra cómo el sistema propone automáticamente una mejora del prompt de un especialista.
- El PR incluye diff, simulación de regresión y checklist para revisión humana.
- Mencionar roadmap Fase 7: CENDOJ, memoria episódica, SSO corporativo, más jurisdicciones LatAm.

---

## Notas para el presentador

- El dataset de evaluación (`evals/golden_dataset/`) tiene `expert_reviewed: false` en todos los casos. Mencionar esto explícitamente: el sistema está en fase MVP, los prompts y el dataset no han sido revisados por un jurista.
- La interfaz está en español; el código y los commits están en inglés (convención del proyecto).
- Si la latencia es alta (> 15 s en shallow, > 70 s en deep), probable causa: primera llamada cold-start del modelo. Las siguientes son más rápidas.
- Costes son estimaciones basadas en precios públicos Anthropic (mayo 2026); pueden variar.
- UK y BR aparecen en el planner pero tienen cobertura limitada de fuentes — siempre mencionar esto en la demo para evitar falsas expectativas.
