# Demo guide — lex-agents v0.1.0

Guion para demostración de 10 minutos. Audiencia: dirección jurídica y cumplimiento.

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

## Notas para el presentador

- El dataset de evaluación (`evals/golden_dataset/`) tiene `expert_reviewed: false` en todos los casos. Mencionar esto explícitamente: el sistema está en fase MVP, los prompts y el dataset no han sido revisados por un jurista.
- La interfaz está en español; el código y los commits están en inglés (convención del proyecto).
- Si la latencia es alta (> 15 s), probable causa: primera llamada cold-start del modelo. Las siguientes son más rápidas.
