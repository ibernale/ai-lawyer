"""Eval runner CLI.

Usage:
    python -m evals run --dataset evals/golden_dataset [--output reports/ts/] [--filter difficulty=hard]
    python -m evals run --dataset evals/golden_dataset_smoke
    python -m evals compare --baseline reports/<a>/ --candidate reports/<b>/
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from evals.runners.metrics import (
    CaseResult,
    RunSummary,
    aggregate_summary,
    compute_caveat_coverage,
    compute_citation_precision,
    compute_citation_recall,
    compute_concept_coverage,
    compute_forbidden_claim_rate,
    compute_hallucination_rate,
    compute_legal_quality_score,
)

# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def load_dataset(dataset_dir: Path, filters: dict[str, str]) -> list[dict[str, Any]]:
    """Load and optionally filter YAML case files from a directory."""
    cases = []
    for path in sorted(dataset_dir.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            case = yaml.safe_load(fh)
        if case is None:
            continue
        # Apply filters
        skip = False
        for key, value in filters.items():
            if str(case.get(key, "")) != value:
                skip = True
                break
        if not skip:
            cases.append(case)
    return cases


def dataset_sha(dataset_dir: Path) -> str:
    """SHA-256 of all YAML files in the dataset, sorted by name."""
    h = hashlib.sha256()
    for path in sorted(dataset_dir.glob("*.yaml")):
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Weights loading
# ---------------------------------------------------------------------------

def load_weights(weights_path: Path | None = None) -> dict[str, float]:
    if weights_path is None:
        weights_path = Path(__file__).parent.parent / "config" / "weights.yaml"
    with weights_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# Orchestrator construction
# ---------------------------------------------------------------------------

def _build_orchestrator() -> Any:
    """Construct Orchestrator from environment variables (no FastAPI dependency)."""
    import anthropic
    from lex_agents_agents.base_agent import AnthropicClientWrapper
    from lex_agents_agents.orchestrator import Orchestrator, OrchestratorDeps
    from lex_agents_agents.regulatorio_bancario import RegulatorioBancarioAgent
    from lex_agents_agents.router import QueryRouter
    from lex_agents_rag.retriever import HybridRetriever
    from lex_agents_verifier.pipeline import VerifierPipeline

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")

    raw_client = anthropic.Anthropic(api_key=api_key)
    client = AnthropicClientWrapper(raw_client)
    retriever = HybridRetriever(qdrant_url=qdrant_url)
    router = QueryRouter(client)
    specialist = RegulatorioBancarioAgent(client)
    verifier = VerifierPipeline(anthropic_client=raw_client)

    deps = OrchestratorDeps(
        router=router,
        specialist=specialist,
        retriever=retriever,
        verifier=verifier,
    )
    return Orchestrator(deps=deps)


# ---------------------------------------------------------------------------
# Single-case runner
# ---------------------------------------------------------------------------

async def _run_case(
    orchestrator: Any,
    case: dict[str, Any],
    weights: dict[str, float],
) -> CaseResult:
    from lex_agents_agents.orchestrator import ConsultRequest

    case_id: str = case.get("id", "unknown")
    branch_expected: str = case.get("branch", "")
    expected: dict[str, Any] = case.get("expected", {})

    t0 = time.perf_counter()
    error: str | None = None
    raw_response: dict[str, Any] = {}

    try:
        query: str = case.get("query", "")
        jurisdiction: list[str] = case.get("jurisdiction", [])
        request = ConsultRequest(
            query=query,
            jurisdiction=jurisdiction if jurisdiction else None,
        )
        response = await orchestrator.run(request)
        latency_ms = (time.perf_counter() - t0) * 1000

        raw_response = response.model_dump() if hasattr(response, "model_dump") else {}

        branch_actual: str = raw_response.get("branch", "")
        routing_correct = branch_actual == branch_expected

        answer_text: str = raw_response.get("answer_text", "")
        citations_raw: list[dict[str, Any]] = raw_response.get("citations", [])

        from lex_agents_shared.types import CitationMapping, VerificationReport

        citations = [CitationMapping(**c) for c in citations_raw]

        verification_raw = raw_response.get("verification")
        if verification_raw:
            report = VerificationReport(**verification_raw)
        else:
            report = VerificationReport(response_id=case_id)

        must_cite = expected.get("must_cite_any_of", [])
        must_mention = expected.get("must_mention_concepts", [])
        must_not = expected.get("must_not_claim", [])
        caveats = expected.get("expected_caveats", [])

        cit_recall = compute_citation_recall(citations, must_cite)
        cit_precision = compute_citation_precision(report)
        hall_rate = compute_hallucination_rate(report)
        concept_cov = compute_concept_coverage(answer_text, must_mention)
        forbidden_rate = compute_forbidden_claim_rate(answer_text, must_not)
        caveat_cov = compute_caveat_coverage(answer_text, caveats)
        cost_usd: float = raw_response.get("cost_estimate_usd", 0.0) or 0.0

        cr = CaseResult(
            case_id=case_id,
            branch_expected=branch_expected,
            branch_actual=branch_actual,
            routing_correct=routing_correct,
            citation_recall=cit_recall,
            citation_precision=cit_precision,
            hallucination_rate=hall_rate,
            concept_coverage=concept_cov,
            forbidden_claim_rate=forbidden_rate,
            caveat_coverage=caveat_cov,
            legal_quality_score=0.0,  # filled below
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            passed=(forbidden_rate == 0.0 and len(report.broken_refs) == 0),
            raw_response=raw_response,
            error=None,
        )
        cr.legal_quality_score = compute_legal_quality_score(cr, weights)
        return cr

    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        error = f"{type(exc).__name__}: {exc}"
        cr = CaseResult(
            case_id=case_id,
            branch_expected=branch_expected,
            branch_actual="",
            routing_correct=False,
            citation_recall=0.0,
            citation_precision=0.0,
            hallucination_rate=1.0,
            concept_coverage=0.0,
            forbidden_claim_rate=0.0,
            caveat_coverage=0.0,
            legal_quality_score=0.0,
            latency_ms=latency_ms,
            cost_usd=0.0,
            passed=False,
            raw_response=raw_response,
            error=error,
        )
        return cr


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _write_results_jsonl(output_dir: Path, results: list[CaseResult]) -> None:
    path = output_dir / "results.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(dataclasses.asdict(r)) + "\n")


def _write_metrics_json(output_dir: Path, summary: RunSummary) -> None:
    path = output_dir / "metrics.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(dataclasses.asdict(summary), fh, indent=2)


def _write_manifest(output_dir: Path, meta: dict[str, Any]) -> None:
    path = output_dir / "manifest.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)


def _write_summary_md(output_dir: Path, summary: RunSummary, results: list[CaseResult]) -> None:
    path = output_dir / "summary.md"
    lines = [
        "# Eval Run Summary",
        "",
        f"**Run ID:** `{summary.run_id}`  ",
        f"**Commit:** `{summary.commit}`  ",
        f"**Timestamp:** {summary.timestamp}  ",
        f"**Dataset SHA:** `{summary.dataset_sha}`  ",
        "",
        "## Aggregate Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| cases_total | {summary.cases_total} |",
        f"| cases_passed | {summary.cases_passed} |",
        f"| cases_failed | {summary.cases_failed} |",
        f"| routing_accuracy | {summary.routing_accuracy:.3f} |",
        f"| citation_recall | {summary.citation_recall:.3f} |",
        f"| citation_precision | {summary.citation_precision:.3f} |",
        f"| hallucination_rate | {summary.hallucination_rate:.3f} |",
        f"| concept_coverage | {summary.concept_coverage:.3f} |",
        f"| forbidden_claim_rate | {summary.forbidden_claim_rate:.3f} |",
        f"| caveat_coverage | {summary.caveat_coverage:.3f} |",
        f"| **legal_quality_score** | **{summary.legal_quality_score:.4f}** |",
        f"| latency_p50 (ms) | {summary.latency_p50:.0f} |",
        f"| latency_p95 (ms) | {summary.latency_p95:.0f} |",
        f"| cost_per_query (USD) | ${summary.cost_per_query:.4f} |",
        "",
        "## Per-Case Results",
        "",
        "| ID | Branch | Routing | Recall | Precision | Hall | Score | Passed | Error |",
        "|----|--------|---------|--------|-----------|------|-------|--------|-------|",
    ]
    for r in results:
        routing = "✓" if r.routing_correct else "✗"
        passed = "✓" if r.passed else "✗"
        err = (r.error or "")[:40] if r.error else ""
        lines.append(
            f"| {r.case_id} | {r.branch_actual or r.branch_expected} | {routing} "
            f"| {r.citation_recall:.2f} | {r.citation_precision:.2f} "
            f"| {r.hallucination_rate:.2f} | {r.legal_quality_score:.3f} | {passed} | {err} |"
        )

    if summary.errors:
        lines += ["", "## Errors", ""]
        for e in summary.errors:
            lines.append(f"- {e}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# run subcommand
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    dataset_dir = Path(args.dataset)
    if not dataset_dir.is_dir():
        print(f"ERROR: dataset directory not found: {dataset_dir}", file=sys.stderr)
        return 1

    # Parse filters: key=value pairs
    filters: dict[str, str] = {}
    for f in args.filter or []:
        if "=" in f:
            k, v = f.split("=", 1)
            filters[k.strip()] = v.strip()

    cases = load_dataset(dataset_dir, filters)
    if not cases:
        print("WARNING: no cases found (check dataset dir or filters)", file=sys.stderr)
        return 0

    weights = load_weights()

    run_id = str(uuid.uuid4())[:8]
    commit = _git_commit()
    ts = datetime.now(UTC).isoformat()
    ds_sha = dataset_sha(dataset_dir)

    output_dir = Path(args.output) if args.output else Path(f"evals/reports/{ts.replace(':', '')[:15]}")
    output_dir.mkdir(parents=True, exist_ok=True)

    meta: dict[str, Any] = {
        "run_id": run_id,
        "git_commit": commit,
        "dataset": str(dataset_dir),
        "dataset_sha": ds_sha,
        "prompt_versions": {},  # populated if orchestrator exposes them
        "models": [],
        "timestamp": ts,
    }

    orchestrator = _build_orchestrator()

    print(f"Running {len(cases)} cases from {dataset_dir} → {output_dir}")
    results: list[CaseResult] = []

    for i, case in enumerate(cases, 1):
        case_id = case.get("id", f"case-{i}")
        print(f"  [{i}/{len(cases)}] {case_id} ...", end=" ", flush=True)
        cr = asyncio.run(_run_case(orchestrator, case, weights))
        status = "PASS" if cr.passed else "FAIL"
        if cr.error:
            status = f"ERROR({cr.error[:30]})"
        print(f"{status} ({cr.latency_ms:.0f}ms)")
        results.append(cr)

    summary = aggregate_summary(results, weights, meta)

    _write_results_jsonl(output_dir, results)
    _write_metrics_json(output_dir, summary)
    _write_manifest(output_dir, meta)
    _write_summary_md(output_dir, summary, results)

    print(f"\nResults written to {output_dir}/")
    print(f"  legal_quality_score: {summary.legal_quality_score:.4f}")
    print(f"  cases: {summary.cases_passed}/{summary.cases_total} passed")
    print(f"  forbidden_claim_rate: {summary.forbidden_claim_rate:.3f}")

    # Non-zero exit if any hard failures
    if summary.forbidden_claim_rate > 0:
        print("FAIL: forbidden_claim_rate > 0", file=sys.stderr)
        return 1

    return 0


# ---------------------------------------------------------------------------
# compare subcommand
# ---------------------------------------------------------------------------

def cmd_compare(args: argparse.Namespace) -> int:
    baseline_dir = Path(args.baseline)
    candidate_dir = Path(args.candidate)

    baseline_file = baseline_dir / "metrics.json"
    candidate_file = candidate_dir / "metrics.json"

    for p in (baseline_file, candidate_file):
        if not p.exists():
            print(f"ERROR: metrics.json not found: {p}", file=sys.stderr)
            return 1

    with baseline_file.open() as fh:
        baseline: dict[str, Any] = json.load(fh)
    with candidate_file.open() as fh:
        candidate: dict[str, Any] = json.load(fh)

    METRICS = [
        "legal_quality_score",
        "citation_recall",
        "citation_precision",
        "hallucination_rate",
        "concept_coverage",
        "forbidden_claim_rate",
        "caveat_coverage",
        "routing_accuracy",
        "latency_p50",
        "latency_p95",
        "cost_per_query",
    ]

    HIGHER_IS_BETTER = {
        "legal_quality_score", "citation_recall", "citation_precision",
        "concept_coverage", "caveat_coverage", "routing_accuracy",
    }

    print(f"\nComparison: {baseline_dir} → {candidate_dir}\n")
    print(f"{'Metric':<30} {'Baseline':>10} {'Candidate':>10} {'Delta':>10} {'Dir':>4}")
    print("-" * 70)

    regressions = []
    for m in METRICS:
        b_val = float(baseline.get(m, 0) or 0)
        c_val = float(candidate.get(m, 0) or 0)
        delta = c_val - b_val
        direction = ""
        if abs(delta) > 0.001:
            if m in HIGHER_IS_BETTER:
                direction = "↑" if delta > 0 else "↓"
            else:
                direction = "↓" if delta > 0 else "↑"

        print(f"{m:<30} {b_val:>10.4f} {c_val:>10.4f} {delta:>+10.4f} {direction:>4}")

        # Regression: legal_quality_score dropped > 5%
        if m == "legal_quality_score" and delta < -0.05:
            regressions.append(f"legal_quality_score dropped by {abs(delta):.4f} (> 0.05 threshold)")

    if regressions:
        print("\nREGRESSION DETECTED:")
        for r in regressions:
            print(f"  - {r}")
        return 1

    print("\nNo regressions detected.")
    return 0


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def cli() -> None:
    parser = argparse.ArgumentParser(
        prog="evals",
        description="lex-agents evaluation runner",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    run_parser = subparsers.add_parser("run", help="Run evaluations against a dataset")
    run_parser.add_argument("--dataset", required=True, help="Path to dataset directory")
    run_parser.add_argument("--output", default=None, help="Output directory for results")
    run_parser.add_argument(
        "--filter",
        action="append",
        metavar="KEY=VALUE",
        help="Filter cases (e.g. --filter difficulty=hard). Repeatable.",
    )

    # compare
    compare_parser = subparsers.add_parser("compare", help="Compare two eval runs")
    compare_parser.add_argument("--baseline", required=True, help="Baseline results directory")
    compare_parser.add_argument("--candidate", required=True, help="Candidate results directory")

    args = parser.parse_args()

    if args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "compare":
        sys.exit(cmd_compare(args))
