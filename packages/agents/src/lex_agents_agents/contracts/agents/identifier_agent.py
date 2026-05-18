"""ContractIdentifierAgent — extracts contract type, parties, and regulatory framework."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import structlog

from lex_agents_agents.contracts.models import ContractMetadata, ContractParty

if TYPE_CHECKING:
    from lex_agents_shared.anthropic_client import AnthropicClientWrapper

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# Cost constants for claude-sonnet-4-6 (cheaper model for extraction tasks)
_INPUT_TOKEN_COST_PER_M = 3.0
_OUTPUT_TOKEN_COST_PER_M = 15.0

_EXTRACTION_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 2048

_JSON_SCHEMA = """{
  "document_type": "<NDA|MSA|SLA|LoanAgreement|CreditFacility|EmploymentContract|DataProcessingAgreement|ServiceAgreement|Guarantee|ISDA|Other>",
  "parties": [
    {
      "name": "<exact legal name>",
      "role": "<lender|borrower|buyer|seller|provider|client|controller|processor|employer|employee|disclosing|receiving>",
      "legal_entity_type": "<SA|SL|foundation|individual|null>"
    }
  ],
  "effective_date": "<ISO8601 or natural language or null>",
  "termination_date": "<ISO8601 or natural language or null>",
  "jurisdiction": ["<ES|EU|UK|US|...>"],
  "governing_law": "<e.g. Derecho español>",
  "applicable_framework": ["<GDPR|CRR|AML|PSD2|...>"],
  "contract_language": "<es|en|...>"
}"""


class ContractIdentifierAgent:
    """Identifies contract type, parties, jurisdiction and applicable regulatory framework."""

    SYSTEM_PROMPT = """Eres un experto jurídico especializado en análisis de contratos bajo derecho español y europeo.

Tu tarea es analizar un contrato y extraer la siguiente información de forma precisa y estructurada:

1. TIPO DE CONTRATO: Clasifica el contrato en una de estas categorías:
   NDA, MSA, SLA, LoanAgreement, CreditFacility, EmploymentContract,
   DataProcessingAgreement, ServiceAgreement, Guarantee, ISDA, Other

2. PARTES: Identifica todas las partes contratantes con su nombre exacto y rol.
   Roles posibles: lender, borrower, buyer, seller, provider, client,
   controller, processor, employer, employee, disclosing, receiving

3. FECHAS: Fecha de entrada en vigor y fecha de terminación (si consta).

4. JURISDICCIÓN Y LEY APLICABLE: Identifica la jurisdicción (ES, EU, UK, US, etc.)
   y la ley que rige el contrato (ej: "Derecho español").

5. MARCO REGULATORIO APLICABLE: Identifica qué regulaciones son relevantes para
   este contrato. Considera: GDPR, LOPDGDD, CRR, CRD, AML (Ley 10/2010),
   PSD2/PSD3, MiFID2, EMIR, Código Civil, Código de Comercio, ET (Estatuto
   de los Trabajadores), LCSP, LSSI, CNMV regulations, BdE regulations, EBA guidelines.

IMPORTANTE: Solo incluye marcos regulatorios que REALMENTE apliquen al contrato.
No inventes información que no esté en el texto.

Responde ÚNICAMENTE con un JSON válido siguiendo el esquema exacto proporcionado.
No incluyas explicaciones fuera del JSON."""

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client

    async def identify(self, contract_text: str, trace_id: str) -> ContractMetadata:
        """Extract contract metadata from full text.

        Uses claude-sonnet-4-6 (cheaper) for structured extraction.
        Falls back to a best-effort ContractMetadata if JSON parsing fails.
        """
        user_content = (
            f"Analiza el siguiente contrato y extrae la información en el esquema JSON:\n\n"
            f"ESQUEMA:\n{_JSON_SCHEMA}\n\n"
            f"CONTRATO:\n{contract_text[:40_000]}"  # limit to ~40k chars to stay in context
        )

        try:
            resp = self._client.messages_create(
                model=_EXTRACTION_MODEL,
                max_tokens=_MAX_TOKENS,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as exc:
            logger.exception(
                "identifier_agent_api_error", trace_id=trace_id, error=str(exc)
            )
            return _fallback_metadata()

        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        cost = (in_tok / 1_000_000 * _INPUT_TOKEN_COST_PER_M) + (
            out_tok / 1_000_000 * _OUTPUT_TOKEN_COST_PER_M
        )
        logger.info(
            "identifier_agent_response",
            trace_id=trace_id,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=round(cost, 6),
        )

        text_block = next(
            (b for b in resp.content if getattr(b, "type", None) == "text"), None
        )
        if text_block is None:
            logger.warning("identifier_agent_empty_response", trace_id=trace_id)
            return _fallback_metadata()

        return _parse_metadata(text_block.text, trace_id)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_metadata(text: str, trace_id: str) -> ContractMetadata:
    """Parse JSON response into ContractMetadata; fall back on failure."""
    # Extract JSON object from response (model may wrap with markdown fences)
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not json_match:
        logger.warning("identifier_agent_no_json", trace_id=trace_id)
        return _fallback_metadata()

    try:
        data: dict[str, Any] = json.loads(json_match.group())
        return ContractMetadata.model_validate(data)
    except Exception as exc:
        logger.warning(
            "identifier_agent_parse_error", trace_id=trace_id, error=str(exc)
        )
        # Attempt a partial recovery
        try:
            return _partial_metadata(data if "data" in dir() else {})  # type: ignore[possibly-undefined]
        except Exception:
            return _fallback_metadata()


def _partial_metadata(data: dict[str, Any]) -> ContractMetadata:
    """Build a best-effort ContractMetadata from a partially-valid dict."""
    raw_parties: list[dict[str, Any]] = data.get("parties", [])
    parties: list[ContractParty] = []
    for p in raw_parties:
        try:
            parties.append(ContractParty.model_validate(p))
        except Exception as exc:
            logger.debug("identifier_party_parse_skip", error=str(exc))
            continue

    return ContractMetadata(
        document_type=data.get("document_type", "Other"),  # type: ignore[arg-type]
        parties=parties,
        effective_date=data.get("effective_date"),
        termination_date=data.get("termination_date"),
        jurisdiction=data.get("jurisdiction", ["ES"]),
        governing_law=data.get("governing_law", "Desconocido"),
        applicable_framework=data.get("applicable_framework", []),
        contract_language=data.get("contract_language", "es"),
    )


def _fallback_metadata() -> ContractMetadata:
    return ContractMetadata(
        document_type="Other",
        parties=[],
        jurisdiction=["ES"],
        governing_law="Desconocido",
        applicable_framework=[],
    )
