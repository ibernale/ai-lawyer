"""Contract evaluation runner — Fase 13D.

Measures obligation recall, risk coverage, compliance coverage, and citation
validity against the golden dataset in evals/golden_dataset/contracts/.

Usage:
    python evals/contract_eval.py                   # live API calls
    python evals/contract_eval.py --skip-api        # validate dataset schema only (CI-safe)
    python evals/contract_eval.py --model sonnet    # override model
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
DATASET_DIR = Path(__file__).parent / "golden_dataset" / "contracts"

# Metric targets
TARGET_OBLIGATION_RECALL = 0.95
TARGET_RISK_COVERAGE = 0.90
TARGET_COMPLIANCE_COVERAGE = 0.80
TARGET_CITATION_VALID = 0.95
TARGET_TYPE_ACCURACY = 0.90

# Spanish stopwords (used in keyword overlap matching)
_STOPWORDS = {
    "de", "del", "la", "las", "los", "el", "en", "a", "por", "para", "con",
    "sin", "sobre", "al", "se", "su", "sus", "un", "una", "es", "que", "y",
    "o", "no", "más", "menos", "ante", "bajo", "cabe", "entre", "hasta",
    "mediante", "salvo", "según", "tras", "durante", "desde",
}


# ---------------------------------------------------------------------------
# Dataset loading + validation
# ---------------------------------------------------------------------------


def load_dataset(directory: Path) -> list[dict[str, Any]]:
    cases = []
    for path in sorted(directory.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        _validate_case(data, path)
        cases.append(data)
    return cases


def _validate_case(data: dict[str, Any], path: Path) -> None:
    required_top = {"id", "filename", "contract_text", "annotations"}
    missing = required_top - data.keys()
    if missing:
        raise ValueError(f"{path}: missing top-level keys: {missing}")

    ann = data["annotations"]
    required_ann = {
        "document_type", "parties", "jurisdiction", "governing_law",
        "applicable_framework", "obligations", "risk_factors", "compliance_findings",
    }
    missing_ann = required_ann - ann.keys()
    if missing_ann:
        raise ValueError(f"{path}: missing annotation keys: {missing_ann}")

    for obl in ann.get("obligations", []):
        if not all(k in obl for k in ("id", "party", "deontic_type", "description", "clause_ref")):
            raise ValueError(f"{path}: obligation missing required fields: {obl}")

    for rf in ann.get("risk_factors", []):
        if not all(k in rf for k in ("category", "severity")):
            raise ValueError(f"{path}: risk_factor missing required fields: {rf}")

    for cf in ann.get("compliance_findings", []):
        if not all(k in cf for k in ("regulation", "status")):
            raise ValueError(f"{path}: compliance_finding missing required fields: {cf}")


# ---------------------------------------------------------------------------
# Keyword overlap matching
# ---------------------------------------------------------------------------


def _keywords(text: str) -> set[str]:
    words = text.lower().split()
    return {w.strip(".,;:()[]") for w in words if w.strip(".,;:()[]") not in _STOPWORDS and len(w) > 2}


def _obligation_matches(annotated: dict[str, Any], output_nodes: list[dict[str, Any]]) -> bool:
    """True if any output node has matching deontic_type and ≥2 keyword overlap."""
    ann_kw = _keywords(annotated["description"])
    ann_type = annotated["deontic_type"]
    for node in output_nodes:
        if node.get("deontic_type") != ann_type:
            continue
        out_kw = _keywords(node.get("description", ""))
        if len(ann_kw & out_kw) >= 2:
            return True
    return False


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def _compute_metrics(
    case: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, float | bool]:
    ann = case["annotations"]

    # Type classification
    type_correct: bool = output.get("metadata", {}).get("document_type") == ann["document_type"]

    # Obligation recall
    annotated_obls = ann["obligations"]
    output_nodes = output.get("obligations", {}).get("nodes", [])
    if annotated_obls:
        matched = sum(1 for obl in annotated_obls if _obligation_matches(obl, output_nodes))
        obligation_recall = matched / len(annotated_obls)
    else:
        obligation_recall = 1.0

    # Risk coverage (category + severity match)
    annotated_risks = ann["risk_factors"]
    output_factors = output.get("risk_assessment", {}).get("factors", [])
    if annotated_risks:
        matched_risk = 0
        for rf in annotated_risks:
            for of in output_factors:
                if of.get("category") == rf["category"] and of.get("severity") == rf["severity"]:
                    matched_risk += 1
                    break
        risk_coverage = matched_risk / len(annotated_risks)
    else:
        risk_coverage = 1.0

    # Compliance coverage (regulation prefix match)
    annotated_cf = ann["compliance_findings"]
    output_cf = output.get("compliance_findings", [])
    if annotated_cf:
        matched_cf = 0
        for acf in annotated_cf:
            prefix = acf["regulation"][:10]
            for ocf in output_cf:
                if ocf.get("regulation", "").startswith(prefix):
                    matched_cf += 1
                    break
        compliance_coverage = matched_cf / len(annotated_cf)
    else:
        compliance_coverage = 1.0

    # Citation validity — count [CLAUSE:N] refs in obligations + risk factors
    num_chunks = len(case["contract_text"].split("\n\nCLÁUSULA "))  # rough chunk count

    def _extract_clause_nums(obj: Any) -> list[int]:
        nums: list[int] = []
        if isinstance(obj, str):
            import re
            for m in re.finditer(r"\[CLAUSE:(\d+)\]", obj):
                nums.append(int(m.group(1)))
        elif isinstance(obj, dict):
            for v in obj.values():
                nums.extend(_extract_clause_nums(v))
        elif isinstance(obj, list):
            for item in obj:
                nums.extend(_extract_clause_nums(item))
        return nums

    all_refs: list[int] = []
    all_refs.extend(_extract_clause_nums(output_nodes))
    all_refs.extend(_extract_clause_nums(output_factors))
    if all_refs:
        valid_refs = sum(1 for n in all_refs if 1 <= n <= max(num_chunks, 1))
        citation_valid_rate = valid_refs / len(all_refs)
    else:
        citation_valid_rate = 1.0

    return {
        "type_correct": type_correct,
        "obligation_recall": obligation_recall,
        "risk_coverage": risk_coverage,
        "compliance_coverage": compliance_coverage,
        "citation_valid_rate": citation_valid_rate,
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _tick(value: float | bool, target: float | None = None) -> str:
    if isinstance(value, bool):
        return "✓" if value else "✗"
    if target is None:
        return "✓" if value >= TARGET_CITATION_VALID else "✗"
    return "✓" if value >= target else "✗"


def _print_results(
    results: list[tuple[dict[str, Any], dict[str, float | bool]]],
) -> bool:
    """Print results table and return True if all aggregate targets are met."""
    print("\nContract Eval Results")
    print("=" * 60)

    # Per-contract
    agg: dict[str, list[float | bool]] = {
        "type_correct": [],
        "obligation_recall": [],
        "risk_coverage": [],
        "compliance_coverage": [],
        "citation_valid_rate": [],
    }
    for case, metrics in results:
        ann = case["annotations"]
        print(f"\n{case['id']} ({ann['document_type']})")
        tc = metrics["type_correct"]
        assert isinstance(tc, bool)
        print(f"  type_correct:          {tc!s:<5}  {_tick(tc)}")
        for key, target in [
            ("obligation_recall", TARGET_OBLIGATION_RECALL),
            ("risk_coverage", TARGET_RISK_COVERAGE),
            ("compliance_coverage", TARGET_COMPLIANCE_COVERAGE),
            ("citation_valid_rate", None),
        ]:
            v = metrics[key]
            assert isinstance(v, float)
            label = f"[target ≥{target:.2f}]" if target else ""
            print(f"  {key:<24} {v:.3f}  {label} {_tick(v, target)}")
            agg[key].append(v)
        agg["type_correct"].append(1.0 if tc else 0.0)

    # Aggregate
    print("\n" + "-" * 60)
    print("AGGREGATE")

    all_pass = True
    targets = {
        "type_accuracy": TARGET_TYPE_ACCURACY,
        "obligation_recall": TARGET_OBLIGATION_RECALL,
        "risk_coverage": TARGET_RISK_COVERAGE,
        "compliance_coverage": TARGET_COMPLIANCE_COVERAGE,
        "citation_valid_rate": None,
    }
    agg_vals = {
        "type_accuracy": float(sum(agg["type_correct"]) / len(agg["type_correct"])),
        "obligation_recall": float(sum(agg["obligation_recall"]) / len(agg["obligation_recall"])),  # type: ignore[arg-type]
        "risk_coverage": float(sum(agg["risk_coverage"]) / len(agg["risk_coverage"])),  # type: ignore[arg-type]
        "compliance_coverage": float(sum(agg["compliance_coverage"]) / len(agg["compliance_coverage"])),  # type: ignore[arg-type]
        "citation_valid_rate": float(sum(agg["citation_valid_rate"]) / len(agg["citation_valid_rate"])),  # type: ignore[arg-type]
    }
    for key, target in targets.items():
        v = agg_vals[key]
        label = f"[target ≥{target:.2f}]" if target else ""
        tick = _tick(v, target)
        print(f"  {key:<24} {v:.3f}  {label} {tick}")
        if target and v < target:
            all_pass = False

    print()
    return all_pass


# ---------------------------------------------------------------------------
# Stub output (--skip-api)
# ---------------------------------------------------------------------------


def _stub_output(case: dict[str, Any]) -> dict[str, Any]:
    """Generate a stub output that partially matches the annotations.
    Used with --skip-api to validate the eval framework itself without API calls.
    The stub intentionally hits the targets to confirm the scoring logic works.
    """
    ann = case["annotations"]

    # Build stub obligations matching all annotated ones
    nodes = []
    for obl in ann["obligations"]:
        nodes.append({
            "id": obl["id"],
            "party": obl["party"],
            "deontic_type": obl["deontic_type"],
            "description": obl["description"],
            "clause_ref": obl["clause_ref"],
            "conditions": None,
            "deadline": None,
            "exceptions": [],
        })

    # Build stub risk factors matching all annotated ones
    factors = []
    for rf in ann["risk_factors"]:
        clause_ref = rf.get("clause_refs", ["[CLAUSE:1]"])[0] if rf.get("clause_refs") else "[CLAUSE:1]"
        factors.append({
            "category": rf["category"],
            "severity": rf["severity"],
            "issue": f"Riesgo identificado en {clause_ref}",
            "confidence": 0.9,
            "clause_refs": rf.get("clause_refs", [clause_ref]),
            "remediation": "Revisar y negociar la cláusula.",
        })

    # Build stub compliance findings
    compliance = []
    for cf in ann["compliance_findings"]:
        compliance.append({
            "regulation": cf["regulation"],
            "status": cf["status"],
            "finding": f"Hallazgo relacionado con {cf['regulation']}",
            "clause_refs": [],
            "recommendation": None,
        })

    return {
        "contract_id": case["id"],
        "metadata": {
            "document_type": ann["document_type"],
            "parties": ann["parties"],
            "jurisdiction": ann["jurisdiction"],
            "governing_law": ann["governing_law"],
            "applicable_framework": ann["applicable_framework"],
        },
        "risk_assessment": {
            "overall_score": 0.5,
            "overall_rating": "yellow",
            "factors": factors,
        },
        "obligations": {"nodes": nodes, "edges": []},
        "compliance_findings": compliance,
    }


# ---------------------------------------------------------------------------
# Live API run
# ---------------------------------------------------------------------------


async def _run_live(cases: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, float | bool]]]:
    # Add packages to path
    import os
    packages_path = REPO_ROOT / "packages" / "agents" / "src"
    shared_path = REPO_ROOT / "packages" / "shared" / "src"
    for p in [str(packages_path), str(shared_path)]:
        if p not in sys.path:
            sys.path.insert(0, p)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set. Use --skip-api for schema-only validation.", file=sys.stderr)
        sys.exit(1)

    from lex_agents_agents.contracts.orchestrator import (
        ContractAnalysisRequest,
        ContractOrchestrator,
    )
    from lex_agents_shared.anthropic_client import AnthropicClientWrapper

    client = AnthropicClientWrapper(api_key=api_key)
    orchestrator = ContractOrchestrator(client)

    results: list[tuple[dict[str, Any], dict[str, float | bool]]] = []
    for case in cases:
        print(f"  Running {case['id']} ({case['annotations']['document_type']})...", end=" ", flush=True)
        req = ContractAnalysisRequest(
            contract_id=case["id"],
            trace_id=f"eval-{case['id']}",
            filename=case["filename"],
            content=case["contract_text"],
        )
        try:
            analysis = await orchestrator.run(req)
            output = json.loads(analysis.model_dump_json())
            print("done")
        except Exception as exc:
            print(f"ERROR: {exc}")
            output = {}
        metrics = _compute_metrics(case, output)
        results.append((case, metrics))

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Contract evaluation runner")
    parser.add_argument("--skip-api", action="store_true", help="Skip API calls, validate dataset schema only")
    parser.add_argument("--model", choices=["sonnet", "opus"], default=None, help="Model override (unused with --skip-api)")
    args = parser.parse_args()

    if not DATASET_DIR.exists():
        print(f"ERROR: Dataset directory not found: {DATASET_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading dataset from {DATASET_DIR}...")
    cases = load_dataset(DATASET_DIR)
    print(f"Loaded {len(cases)} cases")

    if not cases:
        print("ERROR: No cases found in dataset directory.", file=sys.stderr)
        sys.exit(1)

    if args.skip_api:
        print("--skip-api: generating stub outputs (schema validation only)\n")
        results: list[tuple[dict[str, Any], dict[str, float | bool]]] = [
            (case, _compute_metrics(case, _stub_output(case))) for case in cases
        ]
    else:
        print("Running live API calls...\n")
        results = asyncio.run(_run_live(cases))

    all_pass = _print_results(results)

    if not all_pass:
        print("FAIL: one or more aggregate metrics below target", file=sys.stderr)
        sys.exit(1)
    else:
        print("PASS: all aggregate metrics meet targets")


if __name__ == "__main__":
    main()
