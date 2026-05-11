"""Unit tests for evals/runners/run_evals.py — uses mocks, no real API calls."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from evals.runners.run_evals import (
    cmd_compare,
    dataset_sha,
    load_dataset,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_case(
    case_id: str = "TEST-001",
    branch: str = "regulatorio_bancario_ue_es",
    difficulty: str = "easy",
) -> dict:
    return {
        "id": case_id,
        "jurisdiction": ["EU"],
        "branch": branch,
        "difficulty": difficulty,
        "expert_reviewed": False,
        "query": "¿Cuáles son los requisitos CET1?",
        "expected": {
            "must_cite_any_of": [{"type": "regulation", "celex": "32013R0575", "articles": ["92"]}],
            "must_mention_concepts": ["fondos propios"],
            "must_not_claim": [],
            "expected_caveats": [],
            "output_type": "dictamen",
        },
        "notes": "Test case",
    }


def _write_dataset(tmp_path: Path, cases: list[dict]) -> Path:
    ds = tmp_path / "dataset"
    ds.mkdir()
    for c in cases:
        (ds / f"{c['id']}.yaml").write_text(yaml.dump(c), encoding="utf-8")
    return ds


# ---------------------------------------------------------------------------
# test_load_dataset_yaml
# ---------------------------------------------------------------------------

class TestLoadDatasetYaml:
    def test_loads_all_cases(self, tmp_path: Path) -> None:
        cases = [_make_case(f"T-{i:03d}") for i in range(1, 4)]
        ds = _write_dataset(tmp_path, cases)
        loaded = load_dataset(ds, {})
        assert len(loaded) == 3
        assert {c["id"] for c in loaded} == {"T-001", "T-002", "T-003"}

    def test_empty_directory(self, tmp_path: Path) -> None:
        ds = tmp_path / "empty"
        ds.mkdir()
        assert load_dataset(ds, {}) == []

    def test_skips_non_yaml(self, tmp_path: Path) -> None:
        ds = tmp_path / "ds"
        ds.mkdir()
        (ds / "case.yaml").write_text(yaml.dump(_make_case()), encoding="utf-8")
        (ds / "README.md").write_text("# ignored", encoding="utf-8")
        (ds / ".gitkeep").write_text("", encoding="utf-8")
        loaded = load_dataset(ds, {})
        assert len(loaded) == 1


# ---------------------------------------------------------------------------
# test_filter_by_difficulty
# ---------------------------------------------------------------------------

class TestFilterByDifficulty:
    def test_filter_easy(self, tmp_path: Path) -> None:
        cases = [
            _make_case("E-001", difficulty="easy"),
            _make_case("M-001", difficulty="medium"),
            _make_case("H-001", difficulty="hard"),
        ]
        ds = _write_dataset(tmp_path, cases)
        loaded = load_dataset(ds, {"difficulty": "easy"})
        assert len(loaded) == 1
        assert loaded[0]["id"] == "E-001"

    def test_filter_no_match(self, tmp_path: Path) -> None:
        cases = [_make_case("E-001", difficulty="easy")]
        ds = _write_dataset(tmp_path, cases)
        loaded = load_dataset(ds, {"difficulty": "hard"})
        assert loaded == []

    def test_multiple_filters(self, tmp_path: Path) -> None:
        cases = [
            _make_case("B-EU-001", branch="regulatorio_bancario_ue_es", difficulty="easy"),
            _make_case("NEG-001", branch="fuera_de_alcance", difficulty="easy"),
        ]
        ds = _write_dataset(tmp_path, cases)
        loaded = load_dataset(ds, {"difficulty": "easy", "branch": "fuera_de_alcance"})
        assert len(loaded) == 1
        assert loaded[0]["id"] == "NEG-001"


# ---------------------------------------------------------------------------
# test_compare_detects_regression
# ---------------------------------------------------------------------------

class TestCompareDetectsRegression:
    def _write_metrics(self, directory: Path, lqs: float) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        data = {
            "legal_quality_score": lqs,
            "citation_recall": 0.9,
            "citation_precision": 0.9,
            "hallucination_rate": 0.0,
            "concept_coverage": 0.9,
            "forbidden_claim_rate": 0.0,
            "caveat_coverage": 0.9,
            "routing_accuracy": 1.0,
            "latency_p50": 1000.0,
            "latency_p95": 3000.0,
            "cost_per_query": 0.05,
        }
        (directory / "metrics.json").write_text(json.dumps(data))

    def test_regression_returns_exit_1(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline"
        candidate = tmp_path / "candidate"
        self._write_metrics(baseline, lqs=0.85)
        self._write_metrics(candidate, lqs=0.78)  # delta = -0.07, below -0.05 threshold

        args = MagicMock()
        args.baseline = str(baseline)
        args.candidate = str(candidate)
        assert cmd_compare(args) == 1

    def test_no_regression_returns_exit_0(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline"
        candidate = tmp_path / "candidate"
        self._write_metrics(baseline, lqs=0.85)
        self._write_metrics(candidate, lqs=0.84)  # delta = -0.01, within threshold

        args = MagicMock()
        args.baseline = str(baseline)
        args.candidate = str(candidate)
        assert cmd_compare(args) == 0

    def test_improvement_returns_exit_0(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline"
        candidate = tmp_path / "candidate"
        self._write_metrics(baseline, lqs=0.80)
        self._write_metrics(candidate, lqs=0.88)  # improvement

        args = MagicMock()
        args.baseline = str(baseline)
        args.candidate = str(candidate)
        assert cmd_compare(args) == 0

    def test_missing_metrics_returns_error(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline"
        candidate = tmp_path / "candidate"
        candidate.mkdir(parents=True)
        self._write_metrics(baseline, lqs=0.85)
        # candidate has no metrics.json

        args = MagicMock()
        args.baseline = str(baseline)
        args.candidate = str(candidate)
        assert cmd_compare(args) == 1


# ---------------------------------------------------------------------------
# test_manifest_includes_git_sha
# ---------------------------------------------------------------------------

class TestManifestIncludesGitSha:
    def test_git_sha_populated(self) -> None:
        from evals.runners.run_evals import _git_commit
        commit = _git_commit()
        # Should be a short hex string or "unknown"
        assert isinstance(commit, str)
        assert len(commit) > 0

    def test_git_failure_returns_unknown(self) -> None:
        from evals.runners.run_evals import _git_commit
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(128, "git")):
            commit = _git_commit()
        assert commit == "unknown"

    def test_dataset_sha_is_reproducible(self, tmp_path: Path) -> None:
        cases = [_make_case("STABLE-001")]
        ds = _write_dataset(tmp_path, cases)
        sha1 = dataset_sha(ds)
        sha2 = dataset_sha(ds)
        assert sha1 == sha2
        assert len(sha1) == 16

    def test_dataset_sha_changes_on_content_change(self, tmp_path: Path) -> None:
        cases = [_make_case("STABLE-001")]
        ds = _write_dataset(tmp_path, cases)
        sha1 = dataset_sha(ds)
        # Modify file
        (ds / "STABLE-001.yaml").write_text(yaml.dump(_make_case("STABLE-001-modified")))
        sha2 = dataset_sha(ds)
        assert sha1 != sha2
