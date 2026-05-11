"""LDPDecomposer — extracts Legal Data Points from agent responses."""

from __future__ import annotations

import json
import re
import time
from typing import Any

import structlog
from opentelemetry import trace

from lex_agents_shared.anthropic_client import AnthropicClientWrapper, MODEL_OPUS
from lex_agents_shared.types import CitationMapping

from lex_agents_evals_advanced.types import LegalDataPoint

logger: structlog.BoundLogger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

_VALID_CLAIM_TYPES = {"factual", "interpretive", "procedural", "cautionary"}
_VALID_JURISDICTIONS = {"ES", "EU", "ES+EU", "global", "unknown"}
_REF_PATTERN = re.compile(r"\[REF:\d+\]")

_DECOMPOSE_TOOL: dict[str, Any] = {
    "name": "decompose_response",
    "description": "Extract all atomic Legal Data Points from the legal response.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ldps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_text": {"type": "string"},
                        "claim_type": {
                            "type": "string",
                            "enum": ["factual", "interpretive", "procedural", "cautionary"],
                        },
                        "supporting_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "jurisdiction_scope": {
                            "type": "string",
                            "enum": ["ES", "EU", "ES+EU", "global", "unknown"],
                        },
                        "context": {"type": "string"},
                    },
                    "required": [
                        "claim_text", "claim_type", "supporting_refs",
                        "jurisdiction_scope", "context",
                    ],
                },
            }
        },
        "required": ["ldps"],
    },
}

_FALLBACK_SYSTEM = (
    "Eres un extractor de Legal Data Points (LDPs). "
    "Descompón la respuesta jurídica en afirmaciones atómicas verificables."
)


def _load_prompt_body() -> tuple[str, int]:
    """Load decomposer prompt; return (body, max_tokens). Falls back gracefully."""
    try:
        from lex_agents_agents.prompt_loader import load_prompt
        cfg = load_prompt("lemaj/decomposer", version=1)
        return cfg.body, cfg.max_tokens
    except Exception:
        return _FALLBACK_SYSTEM, 4096


def _normalize_claim_type(raw: str) -> str:
    clean = raw.lower().strip()
    return clean if clean in _VALID_CLAIM_TYPES else "factual"


def _normalize_jurisdiction(raw: str) -> str:
    clean = raw.strip()
    return clean if clean in _VALID_JURISDICTIONS else "unknown"


def _extract_refs_from_text(text: str) -> list[str]:
    return _REF_PATTERN.findall(text)


def _heuristic_decompose(answer_text: str, case_id: str) -> list[LegalDataPoint]:
    """Fallback: sentence-split the response into LDPs with minimal metadata."""
    paragraphs = [p.strip() for p in answer_text.split("\n\n") if p.strip()]
    ldps: list[LegalDataPoint] = []
    n = 1
    for para in paragraphs:
        sentences = [s.strip() for s in re.split(r"(?<=[.;])\s+", para) if len(s.strip()) > 30]
        for sentence in sentences:
            refs = _extract_refs_from_text(sentence)
            ldps.append(LegalDataPoint(
                ldp_id=f"{case_id}-LDP-{n}",
                claim_text=sentence,
                claim_type="factual",
                supporting_refs=refs,
                jurisdiction_scope="unknown",
                context=para[:500],
            ))
            n += 1
    logger.warning("decomposer_heuristic_fallback", case_id=case_id, n_ldps=len(ldps))
    return ldps


class LDPDecomposer:
    """Decomposes a legal response into atomic Legal Data Points (LDPs).

    Uses claude-opus-4-7 with tool_use for structured extraction.
    Falls back to heuristic sentence-split on API or parse errors.
    """

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client
        self._body, self._max_tokens = _load_prompt_body()
        logger.info("decomposer_initialized", max_tokens=self._max_tokens)

    def decompose(
        self,
        answer_text: str,
        citations: list[CitationMapping],
        case_id: str,
    ) -> list[LegalDataPoint]:
        """Extract LDPs from answer_text. Always returns at least one LDP."""
        with tracer.start_as_current_span("decomposer.decompose") as span:
            span.set_attribute("case_id", case_id)
            span.set_attribute("model", MODEL_OPUS)

            # Build citation context for the LLM
            cit_context = ""
            if citations:
                lines = [f"[REF:{c.index}] {c.source_id} — {c.hierarchy_path}" for c in citations]
                cit_context = "\n## Referencias disponibles\n" + "\n".join(lines)

            user_msg = (
                f"## Respuesta del agente jurídico\n\n{answer_text}"
                f"{cit_context}"
                "\n\n---\nExtrae todos los LDPs atómicos de esta respuesta."
            )

            t0 = time.monotonic()
            try:
                resp = self._client.messages_create(
                    model=MODEL_OPUS,
                    max_tokens=self._max_tokens,
                    system=self._body,
                    tools=[_DECOMPOSE_TOOL],
                    tool_choice={"type": "any"},
                    messages=[{"role": "user", "content": user_msg}],
                )
            except Exception:
                logger.exception("decomposer_api_error", case_id=case_id)
                return _heuristic_decompose(answer_text, case_id)

            latency = (time.monotonic() - t0) * 1000
            span.set_attribute("latency_ms", round(latency))

            tool_block = next(
                (b for b in resp.content if getattr(b, "type", None) == "tool_use"), None
            )
            if tool_block is None:
                logger.warning("decomposer_no_tool_use", case_id=case_id)
                return _heuristic_decompose(answer_text, case_id)

            try:
                raw: dict[str, Any] = (
                    tool_block.input  # type: ignore[union-attr]
                    if isinstance(tool_block.input, dict)  # type: ignore[union-attr]
                    else json.loads(tool_block.input)  # type: ignore[union-attr]
                )
                ldps = self._parse_ldps(raw.get("ldps", []), case_id, answer_text)
            except Exception:
                logger.exception("decomposer_parse_error", case_id=case_id)
                return _heuristic_decompose(answer_text, case_id)

            if not ldps:
                logger.warning("decomposer_empty_ldps", case_id=case_id)
                return _heuristic_decompose(answer_text, case_id)

            logger.info(
                "decomposer_complete",
                case_id=case_id,
                n_ldps=len(ldps),
                latency_ms=round(latency),
            )
            return ldps

    @staticmethod
    def _parse_ldps(
        raw_list: list[dict[str, Any]],
        case_id: str,
        answer_text: str,
    ) -> list[LegalDataPoint]:
        ldps: list[LegalDataPoint] = []
        for i, item in enumerate(raw_list, start=1):
            claim_text = str(item.get("claim_text", "")).strip()
            if not claim_text:
                continue
            # Enrich supporting_refs: combine LLM output + regex scan
            llm_refs: list[str] = [str(r) for r in item.get("supporting_refs", [])]
            regex_refs = _extract_refs_from_text(claim_text)
            context = str(item.get("context", ""))
            regex_refs += _extract_refs_from_text(context)
            combined_refs = list(dict.fromkeys(llm_refs + regex_refs))  # deduplicate, preserve order

            ldps.append(LegalDataPoint(
                ldp_id=f"{case_id}-LDP-{i}",
                claim_text=claim_text,
                claim_type=_normalize_claim_type(str(item.get("claim_type", "factual"))),  # type: ignore[arg-type]
                supporting_refs=combined_refs,
                jurisdiction_scope=_normalize_jurisdiction(str(item.get("jurisdiction_scope", "unknown"))),  # type: ignore[arg-type]
                context=context[:500],
            ))
        return ldps
