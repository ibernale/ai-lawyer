"""RiskMatrixGenerator — converts a ConsultResponse into a structured risk matrix.

Uses Claude to extract regulatory obligations and classify them by risk level
(Alto / Medio / Bajo) using a standard 3x3 likelihood x impact grid.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

import structlog
from anthropic.types import TextBlock
from lex_agents_shared.anthropic_client import MODEL_SONNET, AnthropicClientWrapper
from pydantic import BaseModel, Field

from lex_agents_agents.core.orchestrator_v2 import ConsultResponse

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Risk levels
# ---------------------------------------------------------------------------

_RISK_GRID: dict[tuple[str, str], str] = {
    ("Alta", "Alto"): "Alto",
    ("Alta", "Medio"): "Alto",
    ("Alta", "Bajo"): "Medio",
    ("Media", "Alto"): "Alto",
    ("Media", "Medio"): "Medio",
    ("Media", "Bajo"): "Bajo",
    ("Baja", "Alto"): "Medio",
    ("Baja", "Medio"): "Bajo",
    ("Baja", "Bajo"): "Bajo",
}


class RiskLevel(StrEnum):
    ALTO = "Alto"
    MEDIO = "Medio"
    BAJO = "Bajo"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class RiskItem(BaseModel):
    regulation: str
    """Normativa aplicable con referencia (e.g. 'CRR Art. 92 [REF:1]')."""
    obligation: str
    """Descripción concisa de la obligación normativa."""
    risk_level: RiskLevel
    """Nivel de riesgo calculado a partir de probabilidad x impacto."""
    likelihood: Literal["Alta", "Media", "Baja"]
    """Probabilidad de incumplimiento."""
    impact: Literal["Alto", "Medio", "Bajo"]
    """Impacto en caso de incumplimiento."""
    mitigation: str
    """Acción de mitigación recomendada."""


class RiskMatrix(BaseModel):
    trace_id: str
    query: str
    items: list[RiskItem]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Eres un experto en gestión de riesgos regulatorios bancarios (UE y España).
Tu función es analizar un análisis jurídico y extraer una matriz de riesgos
estructurada en formato JSON.

Responde ÚNICAMENTE con un array JSON válido de objetos con esta estructura exacta:
[
  {
    "regulation": "<norma con artículo y referencia>",
    "obligation": "<descripción concisa de la obligación>",
    "likelihood": "<Alta|Media|Baja>",
    "impact": "<Alto|Medio|Bajo>",
    "mitigation": "<acción de mitigación concreta>"
  }
]

Reglas:
- Extrae entre 3 y 12 items. Si hay pocos riesgos reales, no infles la lista.
- Usa solo los valores permitidos para likelihood e impact.
- Cita la normativa con el identificador [REF:n] si aparece en el análisis.
- No incluyas ningún texto fuera del array JSON.
"""


def _derive_risk_level(likelihood: str, impact: str) -> RiskLevel:
    key = (likelihood, impact)
    level_str = _RISK_GRID.get(key, "Medio")
    return RiskLevel(level_str)


def _extract_json_array(raw: str) -> list[dict[str, Any]]:
    """Extract the first JSON array from the LLM response (handles markdown fences)."""
    # Strip markdown code fences
    clean = re.sub(r"```(?:json)?\s*", "", raw).strip()
    # Find the first '[' ... ']' block
    m = re.search(r"\[.*\]", clean, re.DOTALL)
    if not m:
        raise ValueError("No JSON array found in LLM response")
    return json.loads(m.group(0))  # type: ignore[no-any-return]


class RiskMatrixGenerator:
    """Generates a RiskMatrix from a ConsultResponse using Claude."""

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client

    def generate(self, response: ConsultResponse, query: str) -> RiskMatrix:
        """Generate a risk matrix synchronously.

        Args:
            response: The ConsultResponse to analyse.
            query:    The original user query.

        Returns:
            A RiskMatrix with items derived from the response.
            Returns an empty matrix on LLM or parse failure rather than raising.
        """
        user_content = (
            f"Consulta original: {query}\n\n"
            f"Análisis jurídico:\n{response.answer}\n\n"
            f"Citas normativas: {json.dumps([c.model_dump() for c in response.citations], ensure_ascii=False)}"
        )

        raw = self._call_llm(user_content)
        items = self._parse_items(raw)

        logger.info(
            "risk_matrix_generated",
            trace_id=response.trace_id,
            n_items=len(items),
        )
        return RiskMatrix(
            trace_id=response.trace_id,
            query=query,
            items=items,
            metadata={
                "model": MODEL_SONNET,
                "source_trace_id": response.trace_id,
            },
        )

    def _call_llm(self, user_content: str) -> str:
        try:
            resp = self._client.messages_create(
                model=MODEL_SONNET,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            text_block = next(
                (b for b in resp.content if isinstance(b, TextBlock)), None
            )
            return text_block.text.strip() if text_block else ""
        except Exception:
            logger.exception("risk_matrix_llm_error")
            return ""

    def _parse_items(self, raw: str) -> list[RiskItem]:
        if not raw:
            return []
        try:
            data = _extract_json_array(raw)
        except Exception:
            logger.warning("risk_matrix_parse_error", raw_snippet=raw[:200])
            return []

        items: list[RiskItem] = []
        for entry in data:
            try:
                likelihood = entry.get("likelihood", "Media")
                impact = entry.get("impact", "Medio")
                risk_level = _derive_risk_level(likelihood, impact)
                items.append(
                    RiskItem(
                        regulation=str(entry.get("regulation", "")),
                        obligation=str(entry.get("obligation", "")),
                        risk_level=risk_level,
                        likelihood=likelihood,
                        impact=impact,
                        mitigation=str(entry.get("mitigation", "")),
                    )
                )
            except Exception:
                logger.warning("risk_matrix_item_parse_error", entry=entry)
        return items
