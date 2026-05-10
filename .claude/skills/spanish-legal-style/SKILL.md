---
name: spanish-legal-style
description: |
  Use this skill when drafting, reviewing, or editing any Spanish-language legal
  output: dictámenes, notas jurídicas, system prompts for specialist agents,
  or legal documentation. Ensures register, terminology, citation format, and
  caveats meet professional jurídico standards.
---

## Register

Write peer-to-peer between lawyers. Not explanatory ("esto significa que..."),
not formal-bureaucratic. Direct, precise, no redundancy.

## First-mention rule

On first mention use the full official name:
- `Reglamento (UE) n.º 575/2013 del Parlamento Europeo y del Consejo`
- `Ley 10/2014, de 26 de junio, de ordenación, supervisión y solvencia de
  entidades de crédito`
- `Real Decreto 84/2015, de 13 de febrero`

On subsequent mentions use accepted abbreviations: CRR, Ley 10/2014, RD 84/2015.
Never invent abbreviations.

## Status markers — always explicit

Every normative reference must carry its current status:
- **Vigente** — in force
- **Derogado/Derogada** — repealed (cite repealing norm)
- **En consulta pública** — open consultation
- **En transposición** — directive in national transposition process
- **Pendiente de desarrollo reglamentario** — awaiting implementing regulation

If status is unknown from retrieved chunks, write: *"El estado de vigencia no
ha podido verificarse con los documentos indexados disponibles."*

## Normative hierarchy (mention when relevant)

```
Reglamento UE (aplicación directa)
  └─ Directiva UE (transpuesta por ley nacional)
       └─ Ley Orgánica
            └─ Ley ordinaria
                 └─ Real Decreto-ley
                      └─ Real Decreto
                           └─ Circular BdE / Guía EBA / Q&A EBA
```

When citing a Circular BdE or Guía EBA, note it is not primary law.

## Citation granularity

Cite with maximum granularity available in the chunk:
`art. 92.1.a) CRR`, `considerando 12 Directiva 2013/36/UE`,
`disposición transitoria tercera, apartado 2`.

Considerandos are preamble, not normative body — mark explicitly:
*"el considerando 47 CRR (no parte dispositiva)"*.

## Grey zones

Do not state categorical conclusions where doctrine or case law is split.
Use:
- *"Podría interpretarse que..."*
- *"La doctrina mayoritaria sostiene que..., aunque existe posición minoritaria..."*
- *"La CNMC/BdE no ha publicado criterio explícito al respecto."*

## Mandatory caveats

Append to every output:

> **Nota:** El presente texto es un borrador de análisis asistido por
> inteligencia artificial con fines de apoyo interno. No constituye
> asesoramiento jurídico y requiere validación por parte de un jurista
> cualificado antes de cualquier uso externo o toma de decisiones.

## What NOT to do

- Do not paraphrase article text without citing it.
- Do not omit the [REF:n] citation for any normative claim.
- Do not use unofficial abbreviations (e.g. "Reg. CRR" → use "CRR").
- Do not state that a norm is "vigente" without a retrieved chunk confirming it.
