---
name: contract-analysis
description: >
  Domain expertise for the lex-agents contract analysis pipeline.
  Covers multi-agent decomposition, structured output schemas, RAG strategy,
  obligation logic, evaluation methodology, and Spanish/EU banking specifics.
  Use this skill when implementing or reviewing any component of Fase 13.
---

# Contract Analysis — Domain Skill

## Architecture Principles

The contract analysis pipeline is a **dedicated orchestration layer** that runs
independently from the consultation PMJ pipeline. It shares infrastructure
(AnthropicClientWrapper, HybridRetriever, Docling, Qdrant, per-tenant DB) but
has its own orchestrator (`ContractOrchestrator`), agent set, API endpoints,
and frontend section (`/contratos`).

### Design Invariants
1. Every factual claim in the analysis MUST cite the source clause (`[CLAUSE:n]`
   notation, analogous to `[REF:n]` in consultations).
2. Risk scores MUST include reasoning chains, not bare numbers.
3. Obligations MUST be encoded in deontic triples: `(party, deontic_type, action)`
   — never free-form prose.
4. The full analysis trace (JSON) is persisted in the `contracts` DB table and
   is retrievable indefinitely.

---

## Agent Decomposition

Six specialized agents, run in two waves:

### Wave 1 — Parallel (after identification)
| Agent | Role | Output |
|-------|------|--------|
| `RiskAnalystAgent` | Clause-level risk scoring (financial, legal, operational, strategic) | `risk_assessment` JSON |
| `ObligationTrackerAgent` | Deontic extraction → obligation graph | `obligations` JSON |
| `ComplianceAgent` | Checks contract against applicable framework (GDPR, CRR, AML, Código Civil) | `compliance_findings` JSON |

### Wave 2 — After Wave 1 (uses Wave 1 output as context)
| Agent | Role | Output |
|-------|------|--------|
| `NegotiationAdvisorAgent` | Market-position benchmarking, party-role stance | `negotiation` JSON |
| `ClauseOptimizerAgent` | Alternative clause language, fallback positions, escalation flags | `clause_alternatives` JSON |

### Sequential steps
1. **ContractIdentifierAgent** (always first): classify type, extract parties,
   detect jurisdiction + governing law, map applicable regulatory framework.
2. Waves 1 and 2 as above.
3. **ContractSynthesizerAgent** (always last): integrates all agent outputs into
   the final `ContractAnalysis` object, resolves conflicts between agents,
   computes the overall risk rating.

---

## Structured Output Schema

```python
class ContractMetadata(BaseModel):
    document_type: str          # NDA | MSA | SLA | LoanAgreement | EmploymentContract | ...
    parties: list[ContractParty]
    effective_date: date | None
    termination_date: date | None
    jurisdiction: list[str]     # ["ES", "EU"]
    governing_law: str          # "Derecho español"
    applicable_framework: list[str]  # ["CRR", "GDPR", "CódigoCivil"]

class RiskFactor(BaseModel):
    category: Literal["financial", "legal", "operational", "strategic"]
    issue: str
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float           # 0.0–1.0
    clause_refs: list[str]      # ["[CLAUSE:3]", "[CLAUSE:7]"]
    remediation: str

class Obligation(BaseModel):
    id: str
    party: str
    deontic_type: Literal["obligation", "permission", "prohibition"]
    description: str
    conditions: str | None
    deadline: date | None
    clause_ref: str

class NegotiationPosition(BaseModel):
    clause_title: str
    current_terms: str
    market_position: str        # what "market standard" looks like
    party_role_stance: str      # recommended position given our role
    alternatives: list[str]     # 2–3 alternative formulations
    escalation_required: bool
    benchmark_source: str       # corpus reference for the benchmark

class ContractAnalysis(BaseModel):
    contract_id: str            # UUID
    trace_id: str               # links to contracts DB table
    metadata: ContractMetadata
    risk_assessment: list[RiskFactor]
    overall_risk_score: float   # 0.0–1.0
    overall_risk_rating: Literal["green", "yellow", "red", "critical"]
    obligations: list[Obligation]
    compliance_findings: list[ComplianceFinding]
    negotiation: list[NegotiationPosition]
    clause_alternatives: list[ClauseAlternative]
    summary: str                # executive summary ≤300 words
    recommendations: list[str]  # prioritised action list
    analysis_trace: dict        # full agent outputs for audit
```

---

## RAG Strategy for Contracts

### Chunking
- **Clause-level**: split at numbered clause boundaries (`1.`, `2.`, `(a)`, `(i)`)
- Preserve parent path: `"Agreement → Section 3 (Representations) → 3.1 (Capacity)"`
- Chunk IDs: `SHA256(contract_id::clause_path)`
- Max chunk size: 800 tokens (contracts have dense legal language)
- Do NOT merge across major sections

### Hybrid Search Weighting (by query type)
| Query type | BM25 weight | Semantic weight |
|------------|-------------|-----------------|
| Definitional ("what does X mean") | 80% | 20% |
| Risk identification | 50% | 50% |
| Obligation extraction | 40% | 60% |
| Cross-contract comparison | 20% | 80% |

### Embedding
- Use existing Voyage AI `voyage-multilingual-2` (platform default)
- No fine-tuning required for v1 — Voyage multilingual handles Spanish legal text
- Future: fine-tune on BOE contracts corpus for v2

### Two Qdrant collections per contract
- `contracts_{tenant_id}`: the uploaded contract, clause-level chunks
- `legal_corpus` (existing): regulatory framework used for compliance checking

---

## Obligation Logic Encoding

Encode obligations in **Defeasible Deontic Logic (DDL)** triples:

```
OBL(party=Vendedor, action=entregar_documentacion, 
    conditions="antes de la fecha de cierre", 
    exceptions=["caso fortuito", "fuerza mayor"],
    source="[CLAUSE:4.2]")
```

Key deontic types:
- `OBL` — obligation (must do)
- `PER` — permission (may do)
- `PRH` — prohibition (must not do)
- `REP` — right (entitled to receive)

Obligation graph edges:
- `depends_on`: B cannot happen until A
- `conflicts_with`: A and B cannot coexist
- `reinforces`: B strengthens A

---

## Negotiation Playbook Architecture

### Playbook structure per contract type
```
playbooks/
  loan_agreement/
    lender.yaml      # our preferred positions when acting as lender
    borrower.yaml    # our preferred positions when acting as borrower
  nda/
    disclosing.yaml
    receiving.yaml
  service_agreement/
    provider.yaml
    client.yaml
```

Each playbook entry:
```yaml
clause: "Limitation of Liability"
preferred_position: "Cap at 12 months fees"
acceptable_positions:
  - "Cap at 24 months fees"
  - "Cap at direct damages only"
fallback_position: "Cap at 36 months fees"
never_accept:
  - "Uncapped liability"
  - "Consequential damages included"
market_benchmark:
  typical_range: "6–24 months fees"
  source: "ISDA market survey 2024 / LMA standard"
escalation_threshold: "Uncapped or >36 months"
```

---

## Evaluation Metrics

| Metric | Target | How to measure |
|--------|--------|----------------|
| Obligation recall | ≥95% | Expert-annotated test contracts |
| Obligation precision | ≥98% | Compare against CUAD annotations |
| Risk flag precision | ≥90% | Senior lawyer review sample |
| Risk flag recall | ≥95% | Must not miss critical risks |
| Citation accuracy | ≥99% | Clause ref maps to correct text |
| Human agreement (κ) | ≥0.80 | Inter-rater on negotiation stances |
| Type classification F1 | ≥0.92 | Held-out contract set |

### Golden dataset
- CUAD (English, 41 clause types) → translated/adapted for Spanish banking
- Internal sample: 20 anonymised Santander contracts (manually annotated)
- Synthetic: 50 contracts generated with known obligation/risk profiles

---

## Spanish/EU Banking Specifics

### Applicable frameworks by contract type
| Contract type | Primary framework |
|---------------|-------------------|
| Loan / Credit facility | CRR Art. 92–134, Código Civil Art. 1740–1757 |
| Collateral / ISDA | EMIR, Código Civil Art. 1857–1886 |
| Data processing (DPA) | GDPR Art. 28–29, LOPDGDD |
| Financial services (PSP) | PSD2/PSD3, Ley 16/2009 |
| Employment | ET Art. 1–55, convenios colectivos |
| Service agreement (bank) | Ley 7/1998 LCGC (standard terms) |
| AML-related | Ley 10/2010 LPBC |

### Risk taxonomy for Spanish banking
1. **Credit risk clauses**: acceleration, cross-default, material adverse change
2. **Regulatory compliance**: prudential ratios, reporting obligations
3. **Data protection**: data controller/processor boundaries, transfer restrictions
4. **Consumer protection**: abusive clauses under Ley 7/1998, transparency requirements
5. **Liability caps**: proportionality vs. CRR capital requirements
6. **Governing law conflicts**: choice-of-law clauses vs. mandatory EU/ES law

---

## Integration Points with Existing Platform

| Component | Integration |
|-----------|-------------|
| `BaseSpecialist` | All 6 agents extend this; inherit `_invoke()`, `_invoke_streaming()`, cost tracking |
| `Docling` | Re-use `DoclingExtractor` for contract PDF/DOCX parsing |
| `HybridRetriever` | Query `contracts_{tenant_id}` + `legal_corpus` collections |
| `ConsultationStore` | New `ContractStore` follows same dual-mode (PG/SQLite) pattern |
| SSE streaming | `ContractOrchestrator.run_streaming()` emits agent-level progress events |
| `/api/v1/documents` | Contracts uploaded via existing multipart endpoint; analysis triggered separately |
| Prompt versioning | All prompts versioned under `contratos/` namespace |
| Admin review queue | Contract analyses appear in review queue with `output_type=analisis_contrato` |
