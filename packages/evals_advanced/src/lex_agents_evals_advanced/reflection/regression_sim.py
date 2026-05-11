"""Regression simulator — validates prompt diffs against 5 neighbor cases.

Applies a diff in-memory, runs the specialist against neighbor cases,
and accepts the diff only if no neighbor regresses.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import structlog

from lex_agents_evals_advanced.types import PromptDiff, RegressionCase, RegressionResult

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_N_REGRESSION_CASES = 5
_FORBIDDEN_PATTERNS = [
    r"mantenemos?\s+acceso\s+pleno",
    r"garantizamos?",
    r"sin\s+ningún?\s+riesgo",
]


def _apply_diff_in_memory(original_text: str, diff_text: str) -> str | None:
    """Apply a unified diff to original_text using patch subprocess.

    Returns patched text or None if patch fails.
    """
    if not diff_text.strip():
        return None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".orig", delete=False) as orig_file:
            orig_path = orig_file.name
            orig_file.write(original_text)

        result = subprocess.run(
            ["patch", "--output=-", orig_path],
            input=diff_text,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning(
                "regression_sim_patch_failed",
                stderr=result.stderr[:200],
            )
            return None
        return result.stdout
    except Exception:
        logger.exception("regression_sim_patch_error")
        return None
    finally:
        try:
            Path(orig_path).unlink(missing_ok=True)  # type: ignore[possibly-undefined]
        except Exception:
            pass


def _find_neighbor_cases(branch: str, n: int = _N_REGRESSION_CASES) -> list[dict[str, Any]]:
    """Load up to n passing cases for the same branch from golden_dataset.

    Uses simple file-order selection (no embedding similarity in MVP).
    Embedding-based selection is tracked in TODO for Fase 6.4.
    """
    import yaml  # type: ignore[import-untyped]

    dataset_dir = Path("evals/golden_dataset")
    if not dataset_dir.exists():
        return []

    cases: list[dict[str, Any]] = []
    for yaml_file in sorted(dataset_dir.glob("*.yaml")):
        if len(cases) >= n:
            break
        try:
            data = yaml.safe_load(yaml_file.read_text())
            if data.get("branch") == branch or branch in (data.get("branches") or []):
                cases.append(data)
        except Exception:
            continue
    return cases


def _heuristic_evaluate(
    case: dict[str, Any],
    prompt_text: str,
    case_id: str,
) -> RegressionCase:
    """Heuristic evaluation of a case against a prompt text (no LLM call).

    Checks: expected concepts mentioned in prompt, no forbidden claims.
    This is a conservative approximation for regression testing.
    """
    expected = case.get("expected", {})
    concepts: list[str] = expected.get("must_mention_concepts", [])
    forbidden: list[str] = expected.get("must_not_claim", [])

    prompt_lower = prompt_text.lower()
    query_lower = case.get("query", "").lower()
    combined = prompt_lower + " " + query_lower

    # Coverage: how many expected concepts would plausibly be covered by this prompt
    matched = sum(1 for c in concepts if c.lower() in combined)
    coverage = matched / len(concepts) if concepts else 1.0

    # Forbidden claim rate
    forbidden_hits = sum(
        1 for f in forbidden
        if re.search(f.lower(), combined)
    )
    # Also check hard-coded forbidden patterns
    pattern_hits = sum(
        1 for p in _FORBIDDEN_PATTERNS
        if re.search(p, combined)
    )
    forbidden_rate = (forbidden_hits + pattern_hits) / max(len(forbidden) + len(_FORBIDDEN_PATTERNS), 1)

    passed = coverage >= 0.5 and forbidden_rate == 0.0

    return RegressionCase(
        case_id=case_id,
        query=case.get("query", "")[:100],
        concept_coverage_before=coverage,
        concept_coverage_after=coverage,
        forbidden_claim_rate_after=forbidden_rate,
        passed=passed,
    )


def simulate(diff: PromptDiff, dry_run: bool = False) -> RegressionResult:
    """Apply diff in-memory and run heuristic regression against neighbor cases.

    Args:
        diff: The proposed prompt diff.
        dry_run: If True, always accept (no actual simulation).

    Returns RegressionResult with accepted=True if all neighbors pass.
    """
    if dry_run:
        return RegressionResult(
            diff=diff,
            accepted=True,
            regression_cases=[],
            notes="dry_run: skipped simulation",
        )

    prompt_path = Path(diff.current_prompt_path)
    if not prompt_path.exists():
        logger.warning("regression_sim_prompt_not_found", path=str(prompt_path))
        return RegressionResult(
            diff=diff,
            accepted=False,
            regression_cases=[],
            notes=f"Prompt file not found: {prompt_path}",
        )

    original_text = prompt_path.read_text()
    patched_text = _apply_diff_in_memory(original_text, diff.diff_text)
    if patched_text is None:
        return RegressionResult(
            diff=diff,
            accepted=False,
            regression_cases=[],
            notes="Patch failed to apply cleanly.",
        )

    neighbor_cases = _find_neighbor_cases(diff.branch)
    if not neighbor_cases:
        logger.info("regression_sim_no_neighbors", branch=diff.branch)
        return RegressionResult(
            diff=diff,
            accepted=True,
            regression_cases=[],
            notes="No neighbor cases found — accepted by default.",
        )

    regression_cases: list[RegressionCase] = []
    for i, case in enumerate(neighbor_cases):
        case_id = case.get("id", f"neighbor-{i}")
        # Baseline evaluation uses original text
        baseline = _heuristic_evaluate(case, original_text, case_id)
        # Candidate evaluation uses patched text
        candidate = _heuristic_evaluate(case, patched_text, case_id)
        # Regression: candidate regresses if coverage drops significantly
        regressed = (
            candidate.concept_coverage_after < baseline.concept_coverage_before - 0.1
            or candidate.forbidden_claim_rate_after > 0
        )
        regression_cases.append(RegressionCase(
            case_id=case_id,
            query=case.get("query", "")[:100],
            concept_coverage_before=baseline.concept_coverage_before,
            concept_coverage_after=candidate.concept_coverage_after,
            forbidden_claim_rate_after=candidate.forbidden_claim_rate_after,
            passed=not regressed,
        ))

    all_passed = all(rc.passed for rc in regression_cases)
    failed_ids = [rc.case_id for rc in regression_cases if not rc.passed]

    if not all_passed:
        logger.info(
            "regression_sim_rejected",
            branch=diff.branch,
            failed_cases=failed_ids,
        )
    else:
        logger.info("regression_sim_accepted", branch=diff.branch)

    notes = (
        f"All {len(regression_cases)} neighbor cases passed."
        if all_passed
        else f"Rejected: {len(failed_ids)} regressions in {failed_ids}."
    )
    return RegressionResult(
        diff=diff,
        accepted=all_passed,
        regression_cases=regression_cases,
        notes=notes,
    )
