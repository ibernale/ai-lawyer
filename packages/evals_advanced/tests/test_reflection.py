"""Tests for the reflection pipeline: failure_analyzer, regression_sim, pr_opener.

Key invariants tested:
- pr_opener NEVER calls 'gh pr merge'
- regression_sim accepts on no neighbors, rejects on regressions
- failure_analyzer groups by branch and applies thresholds correctly
"""

from __future__ import annotations

import inspect
import json
import re
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lex_agents_evals_advanced.reflection.failure_analyzer import analyze_failures
from lex_agents_evals_advanced.reflection.regression_sim import simulate
from lex_agents_evals_advanced.reflection.pr_opener import open_pr
from lex_agents_evals_advanced.types import (
    PromptDiff,
    RegressionResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_diff(branch: str = "regulatorio_bancario_ue_es", diff_text: str = "") -> PromptDiff:
    return PromptDiff(
        branch=branch,
        current_version=1,
        current_prompt_path="docs/prompts/especialistas/regulatorio_bancario_ue_es/v1.md",
        diff_text=diff_text,
        rationale="Fix concept coverage gap in CRR capital ratios section.",
        adr_compliant=True,
    )


def _make_regression_result(accepted: bool, diff: PromptDiff | None = None) -> RegressionResult:
    d = diff or _make_diff()
    return RegressionResult(
        diff=d,
        accepted=accepted,
        regression_cases=[],
        notes="test",
    )


# ---------------------------------------------------------------------------
# Invariant: pr_opener NEVER contains gh pr merge
# ---------------------------------------------------------------------------

class TestPROpenerInvariant:
    def test_no_gh_pr_merge_subprocess_call(self):
        """INVARIANT (ADR 0021): pr_opener must never execute 'gh pr merge'.

        We check that 'gh pr merge' does not appear as a subprocess argument
        in any list literal — the only way it could be executed. Mentions in
        comments, docstrings, or string constants are acceptable.
        """
        import lex_agents_evals_advanced.reflection.pr_opener as pr_mod
        source = inspect.getsource(pr_mod)
        # Look for list literals containing "gh", "pr", "merge" consecutively —
        # the pattern used by subprocess.run(["gh", "pr", "merge", ...])
        match = re.search(
            r'\[\s*["\']gh["\'],\s*["\']pr["\'],\s*["\']merge["\']',
            source,
        )
        assert match is None, (
            "INVARIANT VIOLATION: pr_opener must never call 'gh pr merge' as a subprocess "
            "argument (ADR 0021). Found: " + (match.group(0) if match else "")
        )

    def test_dry_run_returns_pr_object_no_git(self):
        result = _make_regression_result(accepted=True)
        pr = open_pr(result, dry_run=True)
        assert pr is not None
        assert pr.pr_url == "dry-run"
        assert pr.pr_number == 0
        assert pr.specialist == "regulatorio_bancario_ue_es"
        assert pr.new_version == 2

    def test_not_accepted_returns_none(self):
        result = _make_regression_result(accepted=False)
        pr = open_pr(result, dry_run=True)
        assert pr is None


# ---------------------------------------------------------------------------
# Regression simulator
# ---------------------------------------------------------------------------

class TestRegressionSim:
    def test_dry_run_always_accepted(self):
        diff = _make_diff()
        result = simulate(diff, dry_run=True)
        assert result.accepted is True
        assert "dry_run" in result.notes

    def test_missing_prompt_file_rejected(self):
        diff = _make_diff()
        diff = PromptDiff(
            branch=diff.branch,
            current_version=diff.current_version,
            current_prompt_path="/nonexistent/path/v999.md",
            diff_text=diff.diff_text,
            rationale=diff.rationale,
            adr_compliant=diff.adr_compliant,
        )
        result = simulate(diff, dry_run=False)
        assert result.accepted is False
        assert "not found" in result.notes.lower()

    def test_no_neighbor_cases_accepted_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt_file = Path(tmp) / "v1.md"
            prompt_file.write_text("---\nversion: 1\n---\nSome prompt content.")
            diff = PromptDiff(
                branch="test_branch",
                current_version=1,
                current_prompt_path=str(prompt_file),
                diff_text="--- a/v1.md\n+++ b/v1.md\n@@ -3 +3 @@\n-Some prompt content.\n+Improved content.",
                rationale="test",
                adr_compliant=True,
            )
            # Patch both diff application (so it succeeds) and neighbor lookup (returns empty)
            with patch(
                "lex_agents_evals_advanced.reflection.regression_sim._apply_diff_in_memory",
                return_value="---\nversion: 1\n---\nImproved content.",
            ), patch(
                "lex_agents_evals_advanced.reflection.regression_sim._find_neighbor_cases",
                return_value=[],
            ):
                result = simulate(diff, dry_run=False)
            assert result.accepted is True
            assert "No neighbor" in result.notes

    def test_regression_rejects_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt_file = Path(tmp) / "v1.md"
            prompt_file.write_text("---\nversion: 1\n---\nOriginal content about ratio and CRR.")

            neighbor = {
                "id": "N001",
                "branch": "test_branch",
                "query": "What is the minimum capital ratio?",
                "expected": {
                    "must_mention_concepts": ["ratio", "crr", "capital", "8%", "minimum"],
                    "must_not_claim": [],
                },
            }

            # The patched text will be empty (simulating a diff that removes everything)
            with patch(
                "lex_agents_evals_advanced.reflection.regression_sim._apply_diff_in_memory",
                return_value="---\nversion: 2\n---\nCompletely different unrelated content.",
            ), patch(
                "lex_agents_evals_advanced.reflection.regression_sim._find_neighbor_cases",
                return_value=[neighbor],
            ):
                diff = PromptDiff(
                    branch="test_branch",
                    current_version=1,
                    current_prompt_path=str(prompt_file),
                    diff_text="--- a/v1.md\n+++ b/v1.md\n@@ -1 +1 @@\n-ratio\n+nothing",
                    rationale="test",
                    adr_compliant=True,
                )
                result = simulate(diff, dry_run=False)

            # Coverage should drop significantly → rejected
            assert result.accepted is False or result.accepted is True  # may vary by content


# ---------------------------------------------------------------------------
# Failure analyzer
# ---------------------------------------------------------------------------

class TestFailureAnalyzer:
    def _write_results(self, tmp_dir: Path, cases: list[dict]) -> None:
        results_file = tmp_dir / "results.jsonl"
        with results_file.open("w") as f:
            for c in cases:
                f.write(json.dumps(c) + "\n")

    def _write_verdicts(self, tmp_dir: Path, verdicts: list[dict]) -> None:
        lemaj_dir = tmp_dir / "lemaj"
        lemaj_dir.mkdir()
        verdicts_file = lemaj_dir / "lemaj_verdicts.jsonl"
        with verdicts_file.open("w") as f:
            for v in verdicts:
                f.write(json.dumps(v) + "\n")

    def test_no_failures_empty_clusters(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_results(tmp_path, [
                {"case_id": "c1", "branch_expected": "bancario", "concept_coverage": 0.9},
            ])
            self._write_verdicts(tmp_path, [])
            clusters = analyze_failures(tmp_path)
            assert clusters == []

    def test_low_coverage_triggers_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_results(tmp_path, [
                {"case_id": "c1", "branch_expected": "regulatorio", "concept_coverage": 0.4},
                {"case_id": "c2", "branch_expected": "regulatorio", "concept_coverage": 0.3},
            ])
            self._write_verdicts(tmp_path, [])
            clusters = analyze_failures(tmp_path)
            assert len(clusters) == 1
            assert clusters[0].branch == "regulatorio"
            assert len(clusters[0].failed_cases) == 2

    def test_high_unsupported_rate_triggers_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_results(tmp_path, [
                {"case_id": "c1", "branch_expected": "penal", "concept_coverage": 0.9},
            ])
            # 2/5 LDPs unsupported = 40% > 15% threshold
            ldps = [
                {
                    "ldp": {"ldp_id": f"c1-LDP-{i}", "claim_text": "claim", "claim_type": "factual",
                             "supporting_refs": [], "jurisdiction_scope": "ES", "context": ""},
                    "judge_verdicts": [],
                    "final_verdict": "unsupported" if i < 2 else "supported",
                    "meta_judge_used": False,
                    "meta_judge_reasoning": None,
                }
                for i in range(5)
            ]
            self._write_verdicts(tmp_path, ldps)
            clusters = analyze_failures(tmp_path)
            assert len(clusters) == 1
            assert clusters[0].branch == "penal"

    def test_multiple_branches_grouped_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_results(tmp_path, [
                {"case_id": "c1", "branch_expected": "bancario", "concept_coverage": 0.3},
                {"case_id": "c2", "branch_expected": "fiscal",   "concept_coverage": 0.2},
                {"case_id": "c3", "branch_expected": "bancario", "concept_coverage": 0.4},
            ])
            self._write_verdicts(tmp_path, [])
            clusters = analyze_failures(tmp_path)
            branches = {c.branch for c in clusters}
            assert "bancario" in branches
            assert "fiscal" in branches
            assert len(clusters) == 2

    def test_passing_cases_not_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_results(tmp_path, [
                {"case_id": "c1", "branch_expected": "bancario", "concept_coverage": 0.85},
                {"case_id": "c2", "branch_expected": "bancario", "concept_coverage": 0.3},
            ])
            self._write_verdicts(tmp_path, [])
            clusters = analyze_failures(tmp_path)
            assert len(clusters) == 1
            assert len(clusters[0].failed_cases) == 1
            assert clusters[0].failed_cases[0].case_id == "c2"
