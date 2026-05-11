"""CLI entry point for adversarial evaluation.

Usage:
    python -m lex_agents_evals_advanced.adversarial run \\
        --dataset evals/adversarial_dataset/ \\
        [--dry-run] \\
        [--output-dir evals/reports/adversarial_<timestamp>/]

Exit code 1 if any threshold is violated.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import structlog

from .evaluator import AdversarialEvaluator
from .types import RobustnessMetrics

logger = structlog.get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lex_agents_evals_advanced.adversarial",
        description="Adversarial robustness evaluation for lex-agents.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run adversarial evaluation.")
    run_parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="Path to the adversarial dataset directory.",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Use attacked queries as mock responses; no LLM calls.",
    )
    run_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write the JSON report. Defaults to evals/reports/adversarial_<timestamp>/.",
    )
    return parser


def _default_output_dir() -> Path:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return Path("evals/reports") / f"adversarial_{ts}"


def _metrics_to_dict(m: RobustnessMetrics) -> dict:
    return {
        "total_cases": m.total_cases,
        "jailbreak_cases": m.jailbreak_cases,
        "jailbreak_accepted": m.jailbreak_accepted,
        "jailbreak_acceptance_rate": m.jailbreak_acceptance_rate,
        "semantic_similarity_mean": m.semantic_similarity_mean,
        "ldp_divergence_mean": m.ldp_divergence_mean,
        "passed": m.passed,
        "failures": m.failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        dataset_dir: Path = args.dataset
        dry_run: bool = args.dry_run
        output_dir: Path = args.output_dir or _default_output_dir()

        if not dataset_dir.exists():
            logger.error("Dataset directory not found", path=str(dataset_dir))
            return 1

        logger.info(
            "Starting adversarial evaluation",
            dataset=str(dataset_dir),
            dry_run=dry_run,
        )

        evaluator = AdversarialEvaluator()
        metrics = evaluator.evaluate_dataset(dataset_dir=dataset_dir, dry_run=dry_run)

        # Write report
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "robustness_metrics.json"
        with report_path.open("w", encoding="utf-8") as fh:
            json.dump(_metrics_to_dict(metrics), fh, indent=2, ensure_ascii=False)

        logger.info(
            "Evaluation complete",
            passed=metrics.passed,
            total_cases=metrics.total_cases,
            jailbreak_acceptance_rate=metrics.jailbreak_acceptance_rate,
            semantic_similarity_mean=metrics.semantic_similarity_mean,
            ldp_divergence_mean=metrics.ldp_divergence_mean,
            report=str(report_path),
        )

        if not metrics.passed:
            for failure in metrics.failures:
                logger.error("Threshold violation", detail=failure)
            return 1

        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
