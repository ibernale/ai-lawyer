"""CLI entry point for the LeMAJ evaluation runner.

Usage:
    python -m lex_agents_evals_advanced.lemaj run \
        --results-dir evals/reports/<run_id>/ \
        --output-dir evals/reports/<run_id>/lemaj/ \
        [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import structlog
from lex_agents_shared.anthropic_client import AnthropicClientWrapper

from lex_agents_evals_advanced.lemaj.decomposer import LDPDecomposer
from lex_agents_evals_advanced.lemaj.metrics import build_lemaj_metrics, render_report
from lex_agents_evals_advanced.lemaj.panel import JudgePanel
from lex_agents_evals_advanced.types import LDPVerdict

logger: structlog.BoundLogger = structlog.get_logger(__name__)


def _load_case_results(results_dir: Path) -> list[dict]:
    results_file = results_dir / "results.jsonl"
    if not results_file.exists():
        logger.error("lemaj_cli_results_not_found", path=str(results_file))
        return []
    cases = []
    with results_file.open() as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _write_verdicts(output_dir: Path, verdicts_per_case: dict[str, list[LDPVerdict]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / "lemaj_verdicts.jsonl"
    with out_file.open("w") as f:
        for case_verdicts in verdicts_per_case.values():
            for lv in case_verdicts:
                record = {
                    "ldp": {
                        "ldp_id": lv.ldp.ldp_id,
                        "claim_text": lv.ldp.claim_text,
                        "claim_type": lv.ldp.claim_type,
                        "supporting_refs": lv.ldp.supporting_refs,
                        "jurisdiction_scope": lv.ldp.jurisdiction_scope,
                        "context": lv.ldp.context,
                    },
                    "judge_verdicts": [
                        {
                            "judge_id": jv.judge_id,
                            "model": jv.model,
                            "dimensions": {
                                "factual_support": jv.dimensions.factual_support,
                                "normative_accuracy": jv.dimensions.normative_accuracy,
                                "jurisdictional_correctness": jv.dimensions.jurisdictional_correctness,
                                "completeness_partial": jv.dimensions.completeness_partial,
                                "caveat_appropriateness": jv.dimensions.caveat_appropriateness,
                            },
                            "overall": jv.overall,
                            "reasoning": jv.reasoning,
                        }
                        for jv in lv.judge_verdicts
                    ],
                    "final_verdict": lv.final_verdict,
                    "meta_judge_used": lv.meta_judge_used,
                    "meta_judge_reasoning": lv.meta_judge_reasoning,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("lemaj_cli_verdicts_written", path=str(out_file))


async def _run_lemaj(results_dir: Path, output_dir: Path, dry_run: bool) -> int:
    """Core async runner. Returns exit code."""
    case_results = _load_case_results(results_dir)
    if not case_results:
        logger.error("lemaj_cli_no_cases")
        return 1

    run_id = results_dir.name
    client = AnthropicClientWrapper()
    decomposer = LDPDecomposer(client)
    panel = JudgePanel(client)

    verdicts_per_case: dict[str, list[LDPVerdict]] = {}
    coverage_per_case: dict[str, float] = {}
    total_cost = 0.0

    for cr in case_results:
        case_id: str = cr.get("case_id", "unknown")
        answer_text: str = cr.get("answer", "")
        citations: list = cr.get("citations", [])
        context_chunks: str = cr.get("context_chunks", "")
        expected_concepts: list[str] = cr.get("expected_concepts", [])

        if dry_run:
            logger.info("lemaj_cli_dry_run_case", case_id=case_id)
            verdicts_per_case[case_id] = []
            continue

        ldps = decomposer.decompose(answer_text, citations, case_id)
        if not ldps:
            logger.info("lemaj_cli_no_ldps", case_id=case_id)
            verdicts_per_case[case_id] = []
            continue

        case_verdicts = await panel.evaluate_all(ldps, context_chunks)
        verdicts_per_case[case_id] = case_verdicts

        # Simple coverage: fraction of expected concepts found in claim texts
        if expected_concepts:
            all_claims = " ".join(lv.ldp.claim_text.lower() for lv in case_verdicts)
            matched = sum(1 for c in expected_concepts if c.lower() in all_claims)
            coverage_per_case[case_id] = matched / len(expected_concepts)

        logger.info(
            "lemaj_cli_case_done",
            case_id=case_id,
            n_ldps=len(ldps),
            n_verdicts=len(case_verdicts),
        )

    metrics = build_lemaj_metrics(
        verdicts_per_case=verdicts_per_case,
        run_id=run_id,
        cost_usd=total_cost,
        coverage_per_case=coverage_per_case if coverage_per_case else None,
    )

    if not dry_run:
        _write_verdicts(output_dir, verdicts_per_case)

        output_dir.mkdir(parents=True, exist_ok=True)
        metrics_file = output_dir / "lemaj_metrics.json"
        metrics_file.write_text(
            json.dumps(
                {
                    "run_id": metrics.run_id,
                    "timestamp": metrics.timestamp,
                    "cases_evaluated": metrics.cases_evaluated,
                    "total_ldps": metrics.total_ldps,
                    "ldp_supported_rate": metrics.ldp_supported_rate,
                    "ldp_partial_rate": metrics.ldp_partial_rate,
                    "ldp_unsupported_rate": metrics.ldp_unsupported_rate,
                    "ldp_review_required_rate": metrics.ldp_review_required_rate,
                    "coverage_mean": metrics.coverage_mean,
                    "cost_usd": metrics.cost_usd,
                    "fleiss_kappa": metrics.fleiss_kappa,
                    "low_kappa_dimensions": metrics.low_kappa_dimensions,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        human_review = [
            lv
            for case_verdicts in verdicts_per_case.values()
            for lv in case_verdicts
            if lv.final_verdict == "review_required"
        ]
        report_md = render_report(metrics, human_review)
        (output_dir / "lemaj_report.md").write_text(report_md)
        logger.info("lemaj_cli_done", output_dir=str(output_dir))

    # Print summary to stdout
    print(f"\n{'='*60}")
    print(f"LeMAJ run: {run_id}")
    print(f"Cases: {metrics.cases_evaluated} | LDPs: {metrics.total_ldps}")
    print(f"Supported: {metrics.ldp_supported_rate:.1%} | Unsupported: {metrics.ldp_unsupported_rate:.1%}")
    print(f"Review required: {metrics.ldp_review_required_rate:.1%}")
    if metrics.low_kappa_dimensions:
        print(f"⚠️  Low-kappa dimensions: {', '.join(metrics.low_kappa_dimensions)}")
    print("=" * 60)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LeMAJ — Legal Multi-Agent Judge evaluation runner"
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run LeMAJ evaluation on a results directory")
    run_p.add_argument(
        "--results-dir",
        required=True,
        type=Path,
        help="Directory containing results.jsonl",
    )
    run_p.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for lemaj_verdicts.jsonl, lemaj_metrics.json, lemaj_report.md "
             "(defaults to <results-dir>/lemaj/)",
    )
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip API calls — print summary only",
    )

    args = parser.parse_args()

    if args.command != "run":
        parser.print_help()
        sys.exit(1)

    output_dir = args.output_dir or (args.results_dir / "lemaj")
    exit_code = asyncio.run(_run_lemaj(args.results_dir, output_dir, args.dry_run))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
