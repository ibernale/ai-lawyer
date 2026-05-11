"""Legal query rewriter — expands acronyms and synonyms for better retrieval."""

from __future__ import annotations

import structlog
from anthropic import Anthropic
from lex_agents_shared.anthropic_client import MODEL_HAIKU
from pydantic import BaseModel

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
Eres un asistente especializado en normativa bancaria europea y española. \
Tu tarea es reescribir la consulta del usuario expandiendo acrónimos y sinónimos legales \
para mejorar la recuperación de documentos normativos.

Expansiones canónicas que DEBES aplicar:
- CRR → Reglamento (UE) n.º 575/2013 (CRR)
- CRD IV → Directiva 2013/36/UE (CRD IV)
- CET1 → capital de nivel 1 ordinario (Common Equity Tier 1, CET1)
- AT1 → capital adicional de nivel 1 (Additional Tier 1, AT1)
- T2 → capital de nivel 2 (Tier 2, T2)
- MUS → Mecanismo Único de Supervisión (MUS)
- MRU → Mecanismo Único de Resolución (MRU)
- BRRD → Directiva 2014/59/UE (BRRD)
- IFR → Reglamento (UE) 2019/2033 (IFR)
- IFD → Directiva (UE) 2019/2034 (IFD)
- BdE → Banco de España
- BCE → Banco Central Europeo (BCE)
- RRPP → recursos propios
- APR → activos ponderados por riesgo (APR)
- LGD → pérdida en caso de incumplimiento (LGD)
- PD → probabilidad de incumplimiento (PD)
- EAD → exposición en el momento del incumplimiento (EAD)

Responde en JSON con este esquema exacto (sin texto adicional):
{"expanded_query": "...", "added_terms": ["term1", "term2"]}
"""


class RewrittenQuery(BaseModel):
    original: str
    expanded_query: str
    added_terms: list[str]


class LegalQueryRewriter:
    """Expands legal acronyms in queries using claude-haiku."""

    def __init__(self, anthropic_client: Anthropic) -> None:
        self._client = anthropic_client

    def rewrite(self, query: str) -> RewrittenQuery:
        response = self._client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=512,
            temperature=0,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query}],
        )

        raw = response.content[0].text.strip()  # type: ignore[union-attr]

        try:
            import json

            data = json.loads(raw)
            expanded = data.get("expanded_query", query)
            added = data.get("added_terms", [])
        except Exception:
            logger.warning("query_rewrite_parse_error", raw=raw[:200])
            expanded = query
            added = []

        logger.debug(
            "query_rewritten",
            original=query[:80],
            expanded=expanded[:80],
            added_terms=added,
        )
        return RewrittenQuery(original=query, expanded_query=expanded, added_terms=added)
