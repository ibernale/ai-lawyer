"""PR opener — creates prompt-evolution branches and opens GitHub PRs.

POLICY (ADR 0021): This module NEVER auto-merges. It only creates PRs.
CODEOWNERS enforces human review before any prompt file can be merged.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import structlog

from lex_agents_evals_advanced.types import (
    PromptDiff,
    PromptEvolutionPR,
    RegressionResult,
)

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ── INVARIANT: Do NOT add any call to "gh pr merge" in this file. ────────────
# Prompt-evolution PRs require at least one human review (CODEOWNERS + ADR 0021).
# Any automated merge would violate the governance policy.
# ─────────────────────────────────────────────────────────────────────────────


def _bump_version_in_frontmatter(text: str, current_version: int) -> str:
    """Increment MINOR version in YAML frontmatter. E.g. version: 1 → version: 2."""
    new_version = current_version + 1
    return re.sub(
        r"^(version:\s*)\d+",
        f"\\g<1>{new_version}",
        text,
        count=1,
        flags=re.MULTILINE,
    )


def _apply_diff_to_file(prompt_path: Path, diff_text: str) -> bool:
    """Apply a unified diff to the prompt file on disk using `patch`."""
    result = subprocess.run(
        ["patch", str(prompt_path)],
        input=diff_text,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        logger.error(
            "pr_opener_patch_failed",
            path=str(prompt_path),
            stderr=result.stderr[:300],
        )
        return False
    return True


def _git(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _regression_summary(regression_result: RegressionResult) -> str:
    if not regression_result.regression_cases:
        return "No neighbor cases available for regression testing."
    lines = ["| Case | Coverage before | Coverage after | Forbidden rate | Status |",
             "|------|----------------|---------------|---------------|--------|"]
    for rc in regression_result.regression_cases:
        status = "✅" if rc.passed else "❌"
        lines.append(
            f"| {rc.case_id} | {rc.concept_coverage_before:.1%} | "
            f"{rc.concept_coverage_after:.1%} | {rc.forbidden_claim_rate_after:.1%} | {status} |"
        )
    return "\n".join(lines)


def open_pr(
    regression_result: RegressionResult,
    dry_run: bool = False,
) -> PromptEvolutionPR | None:
    """Create a prompt-evolution branch and open a GitHub PR.

    Returns None if:
    - regression_result.accepted is False
    - dry_run is True (prints PR body, no git/gh commands)
    - Git or gh commands fail

    INVARIANT: This function NEVER calls `gh pr merge`.
    """
    if not regression_result.accepted:
        logger.info("pr_opener_skipped_not_accepted", branch=regression_result.diff.branch)
        return None

    diff = regression_result.diff
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    branch_name = f"prompt-evolution/{timestamp}-{diff.branch}"
    new_version = diff.current_version + 1
    prompt_path = Path(diff.current_prompt_path)

    pr_title = f"[prompt-evolution] {timestamp[:8]}: mejora {diff.branch} v{new_version}"

    pr_body = f"""## Prompt Evolution — {diff.branch} v{new_version}

**Generated automatically by the LeMAJ reflection agent.**
> ⚠️ This PR requires human review before merge. CODEOWNERS prevents auto-merge.

### Caso fallido (detonante)

El análisis nightly identificó degradación en el especialista `{diff.branch}`:
- Análisis: {diff.rationale[:500]}

### Diff propuesto

```diff
{diff.diff_text[:3000]}
```

### Simulación de regresión ({len(regression_result.regression_cases)} casos vecinos)

{_regression_summary(regression_result)}

**Resultado**: {'✅ Todos los casos vecinos pasan' if regression_result.accepted else '❌ Regresiones detectadas'}

**Notas**: {regression_result.notes}

### Checklist para revisión humana

- [ ] El cambio no amplía el alcance del especialista sin justificación en ADRs
- [ ] Las cautelas y avisos legales obligatorios se mantienen intactos
- [ ] La simulación de regresión no introduce nuevos fallos en los 5 casos vecinos
- [ ] Un jurista ha revisado el impacto en el tono y alcance del output
- [ ] El cambio es compatible con ADRs 0010–0021
- [ ] Se ha actualizado `manifest.json` con la nueva versión del prompt

---
_Abierto por: lex-agents reflection agent — Fase 6.3_
_ADR de referencia: 0021 (prompt evolution policy)_
"""

    if dry_run:
        logger.info("pr_opener_dry_run", branch=branch_name, title=pr_title)
        print(f"\n{'='*60}")
        print(f"DRY RUN — PR would be created:")
        print(f"Branch: {branch_name}")
        print(f"Title: {pr_title}")
        print(f"Body preview:\n{pr_body[:500]}...")
        print("=" * 60)
        return PromptEvolutionPR(
            branch_name=branch_name,
            pr_url="dry-run",
            pr_number=0,
            specialist=diff.branch,
            new_version=new_version,
            diff_summary=diff.rationale[:200],
        )

    # ── Git operations ────────────────────────────────────────────────────────
    rc, _, err = _git(["checkout", "-b", branch_name])
    if rc != 0:
        logger.error("pr_opener_branch_failed", branch=branch_name, error=err)
        return None

    # Apply diff
    if not _apply_diff_to_file(prompt_path, diff.diff_text):
        _git(["checkout", "main"])
        return None

    # Bump version in frontmatter
    text = prompt_path.read_text()
    bumped = _bump_version_in_frontmatter(text, diff.current_version)
    prompt_path.write_text(bumped)

    # Commit
    _git(["add", str(prompt_path)])
    rc, _, err = _git([
        "commit", "-m",
        f"prompt-evolution({diff.branch}): v{new_version} — {diff.rationale[:80]}\n\n"
        "Co-Authored-By: lex-agents reflection agent <noreply@anthropic.com>",
    ])
    if rc != 0:
        logger.error("pr_opener_commit_failed", error=err)
        _git(["checkout", "main"])
        return None

    _git(["push", "-u", "origin", branch_name])

    # ── Open PR via gh CLI ────────────────────────────────────────────────────
    # INVARIANT: gh pr merge is NEVER called here (ADR 0021 + CODEOWNERS).
    result = subprocess.run(
        [
            "gh", "pr", "create",
            "--title", pr_title,
            "--body", pr_body,
            "--base", "main",
            "--label", "prompt-evolution",
            "--label", "needs-human-review",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("pr_opener_gh_failed", stderr=result.stderr[:300])
        _git(["checkout", "main"])
        return None

    pr_url = result.stdout.strip()
    pr_number_match = re.search(r"/pull/(\d+)", pr_url)
    pr_number = int(pr_number_match.group(1)) if pr_number_match else 0

    logger.info(
        "pr_opener_created",
        branch=branch_name,
        pr_url=pr_url,
        specialist=diff.branch,
        new_version=new_version,
    )

    _git(["checkout", "main"])

    return PromptEvolutionPR(
        branch_name=branch_name,
        pr_url=pr_url,
        pr_number=pr_number,
        specialist=diff.branch,
        new_version=new_version,
        diff_summary=diff.rationale[:200],
    )
