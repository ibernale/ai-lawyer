"""LLM fallback verifier using Haiku — only called for UNCERTAIN claims."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog
from lex_agents_shared.anthropic_client import MODEL_HAIKU, AnthropicClientWrapper
from lex_agents_shared.types import ClaimVerification

from .claim_extractor import Claim

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_VERDICT_MAP: dict[str, str] = {
    "supported": "PASSED",
    "not_supported": "FAILED",
    "partial": "UNCERTAIN",
}


def _find_repo_root(start: Path) -> Path:
    current = start
    for _ in range(20):
        if (current / "pyproject.toml").exists() and (current / "docs").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise FileNotFoundError(f"Could not locate repo root from {start}")


def _load_prompt_body(version: int) -> str:
    repo_root = _find_repo_root(Path(__file__).parent)
    prompt_path = repo_root / "docs" / "prompts" / "verificador" / f"v{version}.md"

    if not prompt_path.exists():
        raise FileNotFoundError(f"Verificador prompt not found: {prompt_path}")

    raw = prompt_path.read_text(encoding="utf-8")

    if not raw.startswith("---"):
        raise ValueError(f"Missing YAML frontmatter in {prompt_path}")

    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Malformed frontmatter in {prompt_path}")

    return parts[2].strip()


class LLMVerifier:
    """LLM fallback verifier for UNCERTAIN claims."""

    def __init__(self, client: AnthropicClientWrapper, prompt_version: int = 1) -> None:
        self._client = client
        self._prompt_version = prompt_version
        self._prompt_body: str | None = None

    def _get_prompt_body(self) -> str:
        if self._prompt_body is None:
            self._prompt_body = _load_prompt_body(self._prompt_version)
        return self._prompt_body

    async def verify_uncertain(
        self,
        claims_with_chunks: list[tuple[Claim, str, ClaimVerification]],
    ) -> list[ClaimVerification]:
        """Process only UNCERTAIN claims via Haiku; return updated list."""
        results: list[tuple[int, ClaimVerification]] = []
        tasks: list[tuple[int, asyncio.Task[ClaimVerification]]] = []

        loop = asyncio.get_running_loop()

        for i, (claim, chunk_text, existing) in enumerate(claims_with_chunks):
            if existing.verdict != "UNCERTAIN":
                results.append((i, existing))
                continue

            task = loop.create_task(
                self._call_haiku(claim, chunk_text, existing)
            )
            tasks.append((i, task))

        if tasks:
            indices = [t[0] for t in tasks]
            awaitables = [t[1] for t in tasks]
            gathered = await asyncio.gather(*awaitables, return_exceptions=True)
            for idx, outcome in zip(indices, gathered):
                original = claims_with_chunks[idx][2]
                if isinstance(outcome, BaseException):
                    logger.warning(
                        "llm_verifier.call_failed",
                        ref_index=original.ref_index,
                        error=str(outcome),
                    )
                    results.append((idx, original))
                else:
                    results.append((idx, outcome))

        # Re-assemble in original order
        ordered: list[ClaimVerification] = [existing for (_, _, existing) in claims_with_chunks]
        for i, cv in results:
            ordered[i] = cv

        return ordered

    async def _call_haiku(
        self,
        claim: Claim,
        chunk_text: str,
        existing: ClaimVerification,
    ) -> ClaimVerification:
        system_prompt = self._get_prompt_body()
        # Use separate user message with XML tags to prevent prompt injection
        # from claim text or chunk content reaching the system instructions.
        user_message = (
            "<claim>\n"
            f"{claim.text}\n"
            "</claim>\n\n"
            "<chunk_text>\n"
            f"{chunk_text}\n"
            "</chunk_text>"
        )

        loop = asyncio.get_running_loop()

        response = await loop.run_in_executor(
            None,
            lambda: self._client.messages_create(
                model=MODEL_HAIKU,
                max_tokens=128,
                temperature=0.0,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            ),
        )

        first = response.content[0] if response.content else None
        raw_text = first.text.strip() if first is not None and hasattr(first, "text") else ""

        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            raw_text = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()

        try:
            parsed = json.loads(raw_text)
            llm_verdict_str = parsed.get("verdict", "partial")
            reason = parsed.get("reason")
            verdict = _VERDICT_MAP.get(llm_verdict_str, "UNCERTAIN")
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "llm_verifier.parse_error",
                ref_index=existing.ref_index,
                raw=raw_text[:200],
                error=str(exc),
            )
            return existing

        confidence_map = {"PASSED": 0.85, "UNCERTAIN": 0.5, "FAILED": 0.15}

        return ClaimVerification(
            ref_index=existing.ref_index,
            verdict=verdict,  # type: ignore[arg-type]
            method="llm_fallback",
            confidence=confidence_map[verdict],
            failure_reason=reason if verdict != "PASSED" else None,
        )
