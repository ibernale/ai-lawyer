---
name: jurisprudence-citation-format
description: |
  Use this skill when an agent generates or reviews citations to court
  decisions (sentencias, autos, providencias) from CENDOJ, Tribunal
  Constitucional, or any other jurisprudential source. Defines exact-match
  requirements, prohibits paraphrasing of holdings without [REF:n] anchoring,
  and mandates clear distinction between ratio decidendi and obiter dicta.
---

## Canonical citation format

Every reference to a court decision must follow this structure:

```
[Tipo] [Número]/[Año], [Tribunal], [Sala], [Fecha], [Ponente si consta]. ECLI:[ECLI si consta]. [REF:n]
```

Examples:

```
STS 1234/2024, Sala de lo Contencioso-Administrativo (Sección 3ª),
de 15 de marzo de 2024, ponente: Excma. Sra. García López.
ECLI:ES:TS:2024:1234. [REF:1]

STC 45/2023, Pleno, de 30 de mayo de 2023. [REF:2]

SAP Madrid (Sección 28ª) 789/2022, de 12 de noviembre de 2022. [REF:3]
```

Abbreviation map:

| Tribunal | Abreviatura |
|----------|-------------|
| Tribunal Supremo | TS / STS |
| Tribunal Constitucional | TC / STC |
| Audiencia Nacional | AN / SAN |
| Tribunal Superior de Justicia | TSJ / STSJ |
| Audiencia Provincial | AP / SAP |
| Juzgado Central de lo Contencioso | JCCA |

## Exact-match requirements (ADR 0024)

The strict verifier checks the following fields against chunk metadata.
**Never include a field in a citation that is not present in the chunk.**

| Field | Rule |
|-------|------|
| Número de recurso | Pattern `\d+/\d{4}` — must appear literally in chunk |
| Año | Must match `decision_date.year` in chunk metadata |
| Sala / Sección | Must appear in `chamber` field of chunk metadata |
| Ponente | Must appear in `judges` list of chunk metadata |
| FJ N | N must be present in `grounds` list of chunk metadata |
| ECLI | Must match `ecli` field exactly if present |

If any of these fields is not confirmed by the chunk, **omit it** from the
citation. Do not invent or infer missing metadata.

## Ratio decidendi vs obiter dicta

**Mandatory distinction.** Every citation to a jurisprudential holding must
clarify its nature:

- **Ratio decidendi**: the legal reasoning that decided the case. Use:
  `"La Sala sostiene como ratio que..."` + `[REF:n]`
- **Obiter dictum**: incidental remark not binding. Use:
  `"La Sala apunta, a título de obiter, que..."` + `[REF:n]`
- **Unknown**: if the chunk does not allow the distinction, include:
  `"(La distinción ratio/obiter requiere lectura íntegra de la resolución.)"

**Prohibited phrasing:**

```
❌ "El Tribunal Supremo sostiene que X."   ← sin cita exacta
❌ "Según jurisprudencia consolidada, X."  ← sin [REF:n]
❌ "En la STS de 2023 se resolvió que X." ← número y fecha incompletos
```

**Correct phrasing:**

```
✓ "La Sala de lo Contencioso-Administrativo del TS ha resuelto que X [REF:1],
   en lo que constituye el ratio de la STS 1234/2024."
```

## Doctrina consolidada vs. pronunciamiento aislado

When citing jurisprudence, always qualify the weight of the precedent:

- **Doctrina consolidada**: cite ≥ 3 consistent decisions from the same chamber.
  Use: `"Doctrina consolidada del TS (entre otras, STS 123/2022 [REF:1],
  STS 456/2021 [REF:2], STS 789/2020 [REF:3])"`
- **Pronunciamiento aislado**: a single decision or minority position.
  Use: `"Pronunciamiento aislado — STS 1234/2024 [REF:1]. No constituye
  doctrina consolidada."`
- **Doctrina superada**: if a more recent decision contradicts older caselaw.
  Use: `"Criterio superado por STS 9999/2024 [REF:2], que abandona el
  anterior sostenido en STS 1111/2019 [REF:1]."`

## Mandatory footer for jurisprudential responses

Any response containing at least one `[REF:n]` with `citation_type =
"jurisprudencia"` must end with:

> *Los fragmentos jurisprudenciales recuperados son extractos parciales.
> La distinción ratio/obiter, la vigencia del criterio y su aplicabilidad
> al caso concreto requieren revisión por jurista cualificado.*

## CENDOJ dev mode notice

If any citation comes from a chunk with `source = "cendoj"`, append at the
end of the response (not inline):

> *Recuperado en modo desarrollo CENDOJ (rate-limited). Uso productivo
> requiere autorización formal del CGPJ, pendiente en fase 8.*
