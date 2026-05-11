"""Entity extraction from legal documents — regex fast-path + LLM fallback."""

from __future__ import annotations

import re
from datetime import date

import structlog

from lex_agents_documents.types import ExtractedEntities

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_NIF_CIF = re.compile(r"\b(?:[A-Z]\d{8}|\d{8}[A-Z])\b")
_ARTICLE = re.compile(r"\bart(?:ículo|iculo)?\.?\s*\d+[\w.]*\b", re.IGNORECASE)
_BOE_REF = re.compile(r"\bBOE-[A-Z]-\d{4}-\d+\b")
_ECLI = re.compile(r"\bECLI:[A-Z]+:[A-Z]+:\d{4}:\w+\b")
_CELEX = re.compile(r"\b\d{1,2}\d{4}[A-Z]\d{4}\b")
_DATE_ISO = re.compile(r"\b\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b")
_DATE_ES = re.compile(
    r"\b\d{1,2}\s+de\s+"
    r"(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|octubre|noviembre|diciembre)\s+de\s+\d{4}\b",
    re.IGNORECASE,
)
_AMOUNT = re.compile(r"\b\d[\d.,]+\s*(?:euros?|EUR|%)\b", re.IGNORECASE)

_SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

_RISK_KEYWORDS = re.compile(
    r"(?:penalización|penalidad|indemnización|responsabilidad|rescisión|"
    r"resolución\s+del\s+contrato|daños\s+y\s+perjuicios|cláusula\s+penal|"
    r"incumplimiento|liquidación)",
    re.IGNORECASE,
)

# LLM fallback threshold: if regex finds fewer than this many total entities.
_LLM_FALLBACK_THRESHOLD = 3
# Max tokens to send to Haiku for entity extraction.
_MAX_LLM_INPUT_TOKENS = 50_000


def _parse_es_date(text: str) -> date | None:
    parts = text.lower().split()
    try:
        day = int(parts[0])
        month = _SPANISH_MONTHS.get(parts[2], 0)
        year = int(parts[4])
        if month:
            return date(year, month, day)
    except (IndexError, ValueError):
        pass
    return None


def _extract_dates(text: str) -> list[date]:
    found: list[date] = []

    for m in _DATE_ISO.finditer(text):
        try:
            found.append(date.fromisoformat(m.group()))
        except ValueError:
            pass

    for m in _DATE_ES.finditer(text):
        d = _parse_es_date(m.group())
        if d:
            found.append(d)

    return list({str(d): d for d in found}.values())


def _extract_risk_clauses(text: str, segments_text: list[str]) -> list[str]:
    """Return short excerpts (≤120 chars) from segments containing risk keywords."""
    risk_excerpts: list[str] = []
    for seg in segments_text:
        for m in _RISK_KEYWORDS.finditer(seg):
            start = max(0, m.start() - 40)
            end = min(len(seg), m.end() + 80)
            excerpt = seg[start:end].replace("\n", " ").strip()
            if excerpt not in risk_excerpts:
                risk_excerpts.append(excerpt)
    return risk_excerpts[:10]  # cap at 10 risk excerpts


class EntityExtractor:
    """Extracts structured entities from document text.

    Uses regex fast-path; falls back to Claude Haiku only when regex
    yields fewer than _LLM_FALLBACK_THRESHOLD entities total.
    """

    def __init__(self, anthropic_client=None) -> None:  # type: ignore[assignment]
        self._client = anthropic_client  # injected; None = no LLM fallback

    def extract(self, text: str, segments_text: list[str] | None = None) -> ExtractedEntities:
        segments_text = segments_text or [text]

        parties = list(dict.fromkeys(_NIF_CIF.findall(text)))

        norms: list[str] = []
        norms += _ARTICLE.findall(text)
        norms += _BOE_REF.findall(text)
        norms += _ECLI.findall(text)
        norms += _CELEX.findall(text)
        norms = list(dict.fromkeys(norms))

        key_dates = _extract_dates(text)
        risk_clauses = _extract_risk_clauses(text, segments_text)

        total = len(parties) + len(norms) + len(key_dates)

        if total < _LLM_FALLBACK_THRESHOLD and self._client is not None:
            llm_entities = self._llm_extract(text)
            parties = list(dict.fromkeys(parties + llm_entities.parties))
            norms = list(dict.fromkeys(norms + llm_entities.norms_referenced))
            if not risk_clauses:
                risk_clauses = llm_entities.risk_clauses

        return ExtractedEntities(
            parties=parties,
            norms_referenced=norms,
            key_dates=key_dates,
            risk_clauses=risk_clauses,
        )

    def _llm_extract(self, text: str) -> ExtractedEntities:
        """Claude Haiku fallback for entity extraction."""
        import json

        # Truncate to avoid exceeding token budget.
        truncated = text[:_MAX_LLM_INPUT_TOKENS]

        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Extrae las siguientes entidades del siguiente texto legal "
                            "y devuelve SOLO JSON con claves: parties (list[str]), "
                            "norms_referenced (list[str]), risk_clauses (list[str]).\n\n"
                            f"TEXTO:\n{truncated}"
                        ),
                    }
                ],
            )
            raw = response.content[0].text.strip()
            # Strip markdown code fences if present.
            if raw.startswith("```"):
                raw = "\n".join(raw.splitlines()[1:-1])
            data = json.loads(raw)
            return ExtractedEntities(
                parties=data.get("parties", []),
                norms_referenced=data.get("norms_referenced", []),
                risk_clauses=data.get("risk_clauses", []),
            )
        except Exception as exc:
            logger.warning("entity_extractor.llm_fallback_failed", error=str(exc))
            return ExtractedEntities()
