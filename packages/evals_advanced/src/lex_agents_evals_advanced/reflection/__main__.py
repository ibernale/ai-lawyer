"""CLI entry point for the reflection-driven prompt evolution runner.

Usage:
    python -m lex_agents_evals_advanced.reflection run \
        --results-dir evals/reports/<run_id>/ \
        [--dry-run]

POLICY (ADR 0021): This runner NEVER auto-merges. It only proposes diffs
and opens PRs for human review.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import structlog
from lex_agents_shared.anthropic_client import AnthropicClientWrapper

from lex_agents_evals_advanced.reflection.failure_analyzer import analyze_failures
from lex_agents_evals_advanced.reflection.pr_opener import open_pr
from lex_agents_evals_advanced.reflection.prompt_proposer import PromptProposer
from lex_agents_evals_advanced.reflection.regression_sim import simulate

logger: structlog.BoundLogger = structlog.get_logger(__name__)


def _run_reflection(results_dir: Path, dry_run: bool) -> int:
    """Core runner. Returns exit code."""
    logger.info("reflection_cli_start", results_dir=str(results_dir), dry_run=dry_run)

    # Step 1: Identify failing branches
    clusters = analyze_failures(results_dir)
    if not clusters:
        logger.info("reflection_cli_no_failures")
        print("No failing branches detected — nothing to propose.")
        return 0

    print(f"\nFailure analysis: {len(clusters)} failing branch(es) detected.")
    for c in clusters:
        print(f"  - {c.branch}: {len(c.failed_cases)} failed cases")

    # Step 2: Generate prompt diffs
    client = AnthropicClientWrapper()
    proposer = PromptProposer(client)
    diffs = proposer.propose_all(clusters)

    if not diffs:
        logger.info("reflection_cli_no_diffs_proposed")
        print("No eligible prompt diffs proposed (protected or prompt not found).")
        return 0

    print(f"\nProposed diffs: {len(diffs)}")
    for d in diffs:
        print(f"  - {d.branch} v{d.current_version} → v{d.current_version + 1}")
        if dry_run:
            print(f"    Rationale: {d.rationale[:200]}")
            if d.diff_text:
                print(f"    Diff preview:\n{d.diff_text[:500]}")

    # Step 3: Regression simulation
    regression_results = [simulate(diff, dry_run=dry_run) for diff in diffs]
    accepted = [r for r in regression_results if r.accepted]
    rejected = [r for r in regression_results if not r.accepted]

    print(f"\nRegression simulation: {len(accepted)} accepted, {len(rejected)} rejected")
    for r in rejected:
        print(f"  ✗ {r.diff.branch}: {r.notes}")
    for r in accepted:
        print(f"  ✓ {r.diff.branch}: {r.notes}")

    if not accepted:
        logger.info("reflection_cli_all_rejected")
        print("All diffs rejected by regression simulation — no PRs to open.")
        return 0

    # Step 4: Open PRs (NEVER auto-merge — ADR 0021)
    prs_opened = 0
    for result in accepted:
        pr = open_pr(result, dry_run=dry_run)
        if pr is not None:
            prs_opened += 1
            if dry_run:
                print(f"\n[DRY RUN] Would open PR for {pr.specialist} v{pr.new_version}")
            else:
                print(f"\n✅ PR opened: {pr.pr_url}")
                print(f"   Branch: {pr.branch_name}")
                print(f"   Specialist: {pr.specialist} v{pr.new_version}")

    logger.info(
        "reflection_cli_done",
        prs_opened=prs_opened,
        dry_run=dry_run,
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reflection — prompt evolution runner (Fase 6.3)"
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run reflection analysis and open PRs if warranted")
    run_p.add_argument(
        "--results-dir",
        required=True,
        type=Path,
        help="Directory containing results.jsonl and lemaj/lemaj_verdicts.jsonl",
    )
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip API calls and git/gh commands — print proposals only",
    )

    args = parser.parse_args()

    if args.command != "run":
        parser.print_help()
        sys.exit(1)

    exit_code = _run_reflection(args.results_dir, args.dry_run)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
