"""Prompt proposer — generates unified diffs for specialist prompt improvements."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import structlog

from lex_agents_shared.anthropic_client import AnthropicClientWrapper, MODEL_OPUS

from lex_agents_evals_advanced.types import FailedCluster, PromptDiff

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# Prompts NOT eligible for evolution (Phase 1 restriction — see ADR 0021)
_PROTECTED_PATHS = frozenset([
    "docs/prompts/router",
    "docs/prompts/planner",
    "docs/prompts/judge",
    "docs/prompts/lemaj",
])

_SPECIALIST_PROMPT_PATTERN = re.compile(
    r"^docs/prompts/especialistas/([a-z_]+)/v(\d+)\.md$"
)

_MAX_FAILED_CASES_IN_PROMPT = 3


def _find_specialist_prompt(branch: str) -> tuple[Path | None, int]:
    """Locate the current versioned prompt file for a specialist branch.

    Returns (path, version) or (None, 0) if not found.
    """
    base = Path("docs/prompts/especialistas") / branch
    if not base.exists():
        return None, 0
    # Find highest version
    candidates = sorted(base.glob("v*.md"), reverse=True)
    if not candidates:
        return None, 0
    path = candidates[0]
    m = re.search(r"v(\d+)\.md$", path.name)
    version = int(m.group(1)) if m else 1
    return path, version


def _is_protected(prompt_path: Path) -> bool:
    path_str = str(prompt_path)
    return any(path_str.startswith(p) for p in _PROTECTED_PATHS)


def _build_proposer_user_msg(
    cluster: FailedCluster,
    prompt_text: str,
    current_version: int,
) -> str:
    cases_section = ""
    for i, fc in enumerate(cluster.failed_cases[:_MAX_FAILED_CASES_IN_PROMPT], 1):
        unsupported_claims = "\n".join(
            f"  - {lv.ldp.claim_text[:200]}"
            for lv in fc.unsupported_ldps[:5]
        )
        cases_section += (
            f"\n### Caso fallido {i}: {fc.case_id}\n"
            f"LDP unsupported rate: {fc.ldp_unsupported_rate:.1%}\n"
            f"Concept coverage: {fc.concept_coverage:.1%}\n"
            f"Claims no soportados:\n{unsupported_claims}\n"
        )

    gaps_section = "\n".join(f"- {g}" for g in cluster.common_gaps[:10])

    return (
        f"## Especialista: {cluster.branch} (prompt v{current_version})\n\n"
        f"## Prompt actual\n\n```\n{prompt_text}\n```\n\n"
        f"## Casos fallidos\n{cases_section}\n\n"
        f"## Razones de los jueces (patrones comunes)\n{gaps_section}\n\n"
        "---\n"
        "Genera un diff unificado (`--- a/... +++ b/...`) que mejore el prompt "
        "para cubrir los gaps detectados. El diff debe:\n"
        "1. Solo modificar el cuerpo del prompt (no frontmatter).\n"
        "2. No ampliar el alcance del especialista más allá de su dominio.\n"
        "3. Mantener todas las cautelas y avisos legales existentes.\n"
        "4. Ser conservador: prefiere añadir ejemplos o aclaraciones, no reescribir.\n"
        "5. Ser compatible con todos los ADRs existentes (0010–0021).\n\n"
        "Responde SOLO con el diff en formato unificado, seguido de `## Rationale` "
        "con una explicación de 2-3 frases."
    )


def _parse_diff_response(text: str) -> tuple[str, str, bool]:
    """Parse LLM response into (diff_text, rationale, adr_compliant).

    Returns ("", "", False) on parse failure.
    """
    diff_match = re.search(r"```(?:diff)?\n(.*?)```", text, re.DOTALL)
    if not diff_match:
        # Try without code fence
        diff_match = re.search(r"(---\s+a/.*?\+\+\+.*?(?=\n##|\Z))", text, re.DOTALL)
    diff_text = diff_match.group(1).strip() if diff_match else ""

    rationale_match = re.search(r"##\s*Rationale\s*\n(.*?)(?:\n##|\Z)", text, re.DOTALL)
    rationale = rationale_match.group(1).strip() if rationale_match else text[-500:]

    # Simple heuristic: flag as non-compliant if LLM mentions expanding scope
    adr_compliant = "⚠️" not in rationale and "expand" not in rationale.lower()

    return diff_text, rationale, adr_compliant


def _build_fallback_diff(prompt_path: Path, current_version: int, branch: str) -> PromptDiff:
    return PromptDiff(
        branch=branch,
        current_version=current_version,
        current_prompt_path=str(prompt_path),
        diff_text="",
        rationale="Proposer unavailable — no diff generated.",
        adr_compliant=True,
    )


class PromptProposer:
    """Generates unified diffs for specialist prompts based on failure clusters."""

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client

    def propose(self, cluster: FailedCluster) -> PromptDiff | None:
        """Generate a diff proposal for one failed branch cluster.

        Returns None if the branch prompt is protected or not found.
        """
        prompt_path, current_version = _find_specialist_prompt(cluster.branch)
        if prompt_path is None:
            logger.warning("proposer_prompt_not_found", branch=cluster.branch)
            return None

        if _is_protected(prompt_path):
            logger.info("proposer_protected_prompt", path=str(prompt_path))
            return None

        prompt_text = prompt_path.read_text()
        user_msg = _build_proposer_user_msg(cluster, prompt_text, current_version)

        t0 = time.monotonic()
        try:
            resp = self._client.messages_create(
                model=MODEL_OPUS,
                max_tokens=2048,
                system=(
                    "Eres un experto en ingeniería de prompts jurídicos. "
                    "Analizas casos fallidos de un sistema RAG legal y propones mejoras "
                    "conservadoras a los prompts de los especialistas. "
                    "NUNCA amplías el alcance del especialista ni eliminas cautelas."
                ),
                messages=[{"role": "user", "content": user_msg}],
            )
        except Exception:
            logger.exception("proposer_api_error", branch=cluster.branch)
            return _build_fallback_diff(prompt_path, current_version, cluster.branch)

        latency = (time.monotonic() - t0) * 1000
        text_block = next(
            (b for b in resp.content if getattr(b, "type", None) == "text"), None
        )
        if text_block is None:
            logger.warning("proposer_empty_response", branch=cluster.branch)
            return _build_fallback_diff(prompt_path, current_version, cluster.branch)

        diff_text, rationale, adr_compliant = _parse_diff_response(text_block.text)  # type: ignore[union-attr]

        if not diff_text:
            logger.warning("proposer_no_diff_parsed", branch=cluster.branch)
            return None

        logger.info(
            "proposer_diff_generated",
            branch=cluster.branch,
            diff_lines=len(diff_text.splitlines()),
            adr_compliant=adr_compliant,
            latency_ms=round(latency),
        )
        return PromptDiff(
            branch=cluster.branch,
            current_version=current_version,
            current_prompt_path=str(prompt_path),
            diff_text=diff_text,
            rationale=rationale,
            adr_compliant=adr_compliant,
        )

    def propose_all(self, clusters: list[FailedCluster]) -> list[PromptDiff]:
        """Generate diffs for all clusters; skip None results."""
        diffs: list[PromptDiff] = []
        for cluster in clusters:
            diff = self.propose(cluster)
            if diff is not None:
                diffs.append(diff)
        return diffs
