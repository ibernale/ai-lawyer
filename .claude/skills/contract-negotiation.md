---
name: contract-negotiation
description: >
  Negotiation strategy and playbook architecture for AI-assisted contract
  negotiation in the lex-agents platform. Covers party-role stance,
  market benchmarking, alternative clause generation, escalation logic,
  and playbook YAML format. Use when implementing NegotiationAdvisorAgent
  or ClauseOptimizerAgent, or when writing negotiation system prompts.
---

# Contract Negotiation — Domain Skill

## Core Principles

1. **Party-role awareness**: negotiation stance is always relative to our role
   (bank/lender/buyer/provider/etc). The same clause is evaluated differently
   depending on who we represent.
2. **Market benchmarking**: "market standard" is an empirical claim, not an
   opinion. Every benchmark must reference a corpus or authoritative source.
3. **Layered positions**: preferred → acceptable → fallback → never-accept.
   Each transition has an explicit trigger condition.
4. **Escalation clarity**: the system flags human review when risk exceeds
   thresholds; it NEVER silently accept an out-of-policy clause.
5. **Alternative language, not just flags**: the most valuable output is a
   ready-to-use alternative clause, not just a warning.

---

## Playbook System

### Directory structure
```
packages/agents/src/lex_agents_agents/contracts/playbooks/
  loan_agreement/
    lender.yaml
    borrower.yaml
  nda/
    disclosing_party.yaml
    receiving_party.yaml
  service_agreement/
    provider.yaml
    client.yaml
  data_processing_agreement/
    controller.yaml
    processor.yaml
  isda_master/
    dealer.yaml
    end_user.yaml
  employment/
    employer.yaml
```

### Playbook entry schema
```yaml
# Required fields
clause_title: "Limitation of Liability"
applicable_contract_types:
  - loan_agreement
  - service_agreement
party_role: lender          # who we represent

# Positions (ordered: preferred → never_accept)
preferred_position:
  summary: "Bilateral cap at 12 months' fees, excluding fraud and wilful misconduct"
  template_language: |
    "Each party's aggregate liability under this Agreement shall not exceed
    the total fees paid in the twelve (12) months preceding the relevant
    claim, except in cases of fraud, gross negligence or wilful misconduct."
  market_prevalence: 0.62   # 62% of executed agreements use this or narrower cap

acceptable_positions:
  - summary: "Cap at 24 months' fees"
    condition: "Counterparty is a regulated financial institution"
    market_prevalence: 0.25
  - summary: "Cap at direct damages only, uncapped quantum"
    condition: "Only if consequential damages explicitly waived by both parties"
    market_prevalence: 0.08

fallback_position:
  summary: "Cap at 36 months' fees, direct damages only"
  requires_approval_from: "Legal Counsel"
  note: "Absolute floor; any concession beyond this requires escalation."

never_accept:
  - condition: "Uncapped liability"
    reason: "Incompatible with CRR Art. 92 capital adequacy requirements"
  - condition: "Consequential damages included without mutual cap"
    reason: "Asymmetric risk profile; prohibited under internal risk policy"

# Escalation
escalation_triggers:
  - "Liability cap exceeds 36 months"
  - "Indemnification covers regulatory fines"
  - "No carve-out for fraud or wilful misconduct"
escalation_to: "Head of Legal / Risk Committee"

# Benchmarking
market_benchmark:
  source: "LMA standard loan agreement 2024 / ISDA master 2002"
  typical_range: "6–24 months for services; 100% notional for financial instruments"
  spanish_law_note: |
    Under Spanish law (Código Civil Art. 1102), liability for dolo (fraud) 
    cannot be excluded or limited by agreement. Any clause attempting to do 
    so is null and void per Art. 6.3 CC.

# Red flags (automatic detection triggers)
red_flags:
  - pattern: "unlimited|ilimitada|sin límite"
    severity: critical
    note: "Uncapped liability clause detected"
  - pattern: "incluyendo.*daños indirectos|including.*indirect damages"
    severity: high
    note: "Consequential damages included — review cap applicability"
```

---

## NegotiationAdvisorAgent Prompt Contract

The system prompt for `NegotiationAdvisorAgent` MUST instruct Claude to:

1. **Identify each substantive clause** in the contract and match it against the
   active playbook for the detected `(contract_type, party_role)` combination.
2. For each matched clause:
   - State which position in the playbook it corresponds to (preferred/acceptable/
     fallback/never-accept/not-covered)
   - Compute market percentile: 0.0 = maximally favourable to us, 1.0 = maximally
     favourable to counterparty
   - Flag escalation if triggered
3. For unmatched clauses (not in playbook): flag as "requires manual review" with
   a description of the risk dimension.
4. Output a `NegotiationSummary` with:
   - Overall negotiation posture score (0=must renegotiate, 1=accept as-is)
   - Prioritised list of clauses to renegotiate (sorted by severity + market distance)
   - Three-scenario analysis: (a) accept all, (b) renegotiate priority clauses,
     (c) full renegotiation

### Output format
```json
{
  "posture_score": 0.0–1.0,
  "posture_label": "reject|renegotiate|conditionally_accept|accept",
  "priority_issues": [
    {
      "clause_title": "string",
      "clause_ref": "[CLAUSE:n]",
      "current_position": "string",
      "playbook_position": "preferred|acceptable|fallback|never_accept|uncharted",
      "market_percentile": 0.0–1.0,
      "recommended_action": "string",
      "alternative_language": "string",
      "escalation_required": true|false
    }
  ],
  "scenarios": {
    "accept_as_is": { "risk_summary": "...", "residual_risks": [] },
    "renegotiate_priority": { "target_clauses": [], "expected_outcome": "..." },
    "full_renegotiation": { "opening_position": "...", "walk_away_conditions": [] }
  }
}
```

---

## ClauseOptimizerAgent Prompt Contract

The system prompt for `ClauseOptimizerAgent` MUST instruct Claude to:

1. For each clause flagged by `NegotiationAdvisorAgent` as needing improvement:
   - Generate 2–3 alternative formulations in the same language as the contract
   - Order alternatives from most to least favourable to us
   - Each alternative must be a complete, drop-in replacement (not a comment)
   - Tag each alternative: `balanced` / `favourable_to_us` / `compromise`
2. For clauses that require Spanish law compliance corrections:
   - Identify the mandatory legal provision violated
   - Generate compliant language that also serves our negotiation interest
3. Output in `ClauseAlternatives` format (one entry per flagged clause)

### Output format
```json
{
  "clause_alternatives": [
    {
      "clause_title": "string",
      "clause_ref": "[CLAUSE:n]",
      "original_text": "string",
      "alternatives": [
        {
          "label": "favourable_to_us",
          "text": "string (complete clause text)",
          "rationale": "string",
          "market_prevalence": 0.0–1.0
        }
      ],
      "mandatory_law_issues": [
        {
          "provision": "CC Art. 1102",
          "issue": "Attempts to limit liability for dolo — null and void",
          "compliant_formulation": "string"
        }
      ]
    }
  ]
}
```

---

## Market Benchmarking Sources

For Spanish/EU banking contracts, benchmark against:

| Contract type | Primary source | Secondary source |
|---------------|---------------|-----------------|
| Loan agreements | LMA (Loan Market Association) standard docs | CNMV/BdE standard terms |
| ISDA/derivatives | ISDA Master Agreement 2002 | ISDA Spain annexes |
| Data processing | EDPB standard contractual clauses | AEPD model DPA |
| Service agreements | ABA model contract | ICLG Spain chapter |
| Employment | CC español / ET | Convenio colectivo banca |
| NDA | ICC model NDA | Custom Santander standard |

When a benchmark is unavailable: state explicitly "No market benchmark available
for this clause in the Spanish banking context — manual review required."

---

## Escalation Decision Tree

```
Is clause in "never_accept" list?
  YES → ESCALATE_CRITICAL (block contract)
  NO ↓

Is market_percentile > 0.85 (very unfavourable)?
  YES → Is it a core commercial term (price, duration, liability)?
    YES → ESCALATE_HIGH (renegotiate before signing)
    NO  → FLAG_MEDIUM (note in report, proceed with caveat)
  NO ↓

Is clause in "fallback" territory?
  YES → ESCALATE_LOW (flag for Legal Counsel review)
  NO  → ACCEPTABLE (include in report, no escalation)
```

---

## Contract-Type × Party-Role Matrix

Playbooks that MUST exist at launch (Fase 13C):

| Contract type | Party roles | Priority |
|---------------|-------------|----------|
| Loan agreement (préstamo) | lender, borrower | P0 |
| NDA (confidencialidad) | disclosing, receiving | P0 |
| Service agreement (servicios) | provider, client | P0 |
| Data processing (DPA) | controller, processor | P0 |
| ISDA Master | dealer, end_user | P1 |
| Employment (laboral) | employer | P1 |
| Credit facility (crédito) | lender, borrower | P1 |
| Guarantee (aval/fianza) | guarantor, beneficiary | P2 |
| Lease (arrendamiento) | landlord, tenant | P2 |

---

## Negotiation Trace Requirements

Every negotiation analysis MUST persist in the `contract_analyses` JSON:
- Playbook version used (semver: `loan_agreement/lender@1.2.0`)
- Market benchmark sources accessed
- Each clause's evaluated position + percentile
- Escalation decisions with reasons
- Analyst who reviewed (if human review occurred)
- Timestamp of analysis

This creates an immutable negotiation history per contract enabling:
- "Why did we accept this clause?" queries
- Benchmark drift analysis over time
- Regulatory audit trail (BdE/BCE supervisory review)
