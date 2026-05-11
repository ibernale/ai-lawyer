> **BORRADOR GENERADO AUTOMÁTICAMENTE**
>
> `expert_reviewed` es `false` en todos los casos de este dataset.
> **NO debe usarse como ground truth** hasta que un jurista cualificado
> revise y firme cada caso individualmente.
> La validación experta es **prerrequisito** de cualquier despliegue corporativo.

# Golden Dataset — Regulatorio Bancario

25 casos bancarios + 5 negativos. Usados para medir calidad jurídica del sistema
en cada release y bloquear regresiones en CI.

## Estructura

```
golden_dataset/
  BANK-EU-001.yaml  ...  BANK-EU-025.yaml   # casos bancarios
  NEG-001.yaml      ...  NEG-005.yaml        # fuera de alcance
  README.md
```

## Schema

```yaml
id: BANK-EU-001
jurisdiction: [ES, EU]
branch: regulatorio_bancario_ue_es
difficulty: easy | medium | hard
expert_reviewed: false
query: "..."
expected:
  must_cite_any_of:
    - { type: regulation, celex: "...", articles: ["..."] }
  must_mention_concepts: ["..."]
  must_not_claim: ["..."]
  expected_caveats: ["..."]
  output_type: dictamen | analisis_riesgo | resumen
notes: "..."
```

## Dificultad

- **easy**: consulta directa, una norma, sin ambigüedad
- **medium**: norma UE + transposición ES, puede haber divergencia
- **hard**: lagunas normativas, normas en consulta, conflictos entre normas

## Autoría

Generado automáticamente como punto de partida. Para promover un caso a
`expert_reviewed: true`, un jurista cualificado debe revisar y firmar en PR.
