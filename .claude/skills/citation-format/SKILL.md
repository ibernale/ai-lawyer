---
name: citation-format
description: |
  Use this skill when implementing or reviewing the citation system: in-text
  [REF:n] markers, the chunk-to-citation mapping structure, rules for when
  citations are mandatory, and how to render human-readable canonical citations
  from chunk metadata.
---

## In-text format

Use `[REF:n]` where `n` is a 1-based integer index into the context mapping
provided to the agent. Place immediately after the claim it supports.

```
El ratio de capital de nivel 1 ordinario mínimo es del 4,5 % [REF:1] de
los activos ponderados por riesgo, según lo establecido en el artículo 92
del CRR [REF:1].
```

One claim may have multiple citations: `[REF:1][REF:3]`.
Multiple claims must not share a single `[REF:n]` if they reference
different granular points within the same article.

## Context mapping structure

The mapping is passed to the agent as structured context and stored with
the response:

```python
class CitationMapping(BaseModel):
    index: int                # matches [REF:n]
    chunk_id: str
    source_id: str            # ELI / CELEX / BOE ID
    hierarchy_path: str       # "CRR > art. 92 > apt. 1.a"
    fragment_text: str        # the relevant sentence(s) from the chunk
    fragment_offset: int      # char offset within chunk for exact location
```

## Mandatory citation rules

1. Every normative or jurisprudential claim → at least one `[REF:n]`
2. Procedural descriptions ("the process consists of...") → citation if
   grounded in regulation, otherwise label as general explanation
3. Dates, article numbers, amounts, percentages → always cite
4. If no supporting chunk exists in the retrieved context:
   - Do **not** fabricate a citation
   - Write: *"No se ha recuperado documentación de soporte para esta
     afirmación en el índice disponible."*

## Forbidden patterns

- `[REF:0]` — indices are 1-based
- Citing a chunk that does not contain the claimed information
- Using a considerando as normative authority without noting it is preamble
- Citing article X when the retrieved chunk is article Y

## Canonical citation rendering (output layer)

The API renders `[REF:n]` into human-readable form using chunk metadata:

```
[REF:1] → Reglamento (UE) n.º 575/2013 (CRR), art. 92, apt. 1.a)
[REF:2] → BOE-A-2014-6732 (Ley 10/2014), art. 69.2
```

Rendering format: `<norm_name_short>, <hierarchy_path_leaf>`

For sentencias (future): `STS <sala> <date>, FJ <n>`

## Verification gate

Before any response is returned to the user, the `verifier` package checks
each `[REF:n]`: does `fragment_text` from that chunk semantically support
the claim? If verification fails for any claim, the response is either:
- Marked with a warning badge (`⚠ cita no verificada`) for human review, or
- Blocked (configurable per deployment)
