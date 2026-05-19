"""ObligationTrackerAgent — extracts DDL obligation triples from contract clauses."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import structlog

from lex_agents_agents.contracts.chunker import ContractChunk
from lex_agents_agents.contracts.models import (
    ContractMetadata,
    Obligation,
    ObligationEdge,
    ObligationGraph,
)

if TYPE_CHECKING:
    from lex_agents_shared.anthropic_client import AnthropicClientWrapper

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096

_JSON_SCHEMA = """{
  "nodes": [
    {
      "id": "<OBL|PER|PRH|REP>-<N>",
      "party": "<nombre de la parte>",
      "deontic_type": "<obligation|permission|prohibition|right>",
      "description": "<descripción concisa de la obligación>",
      "conditions": "<condición activadora o null>",
      "deadline": "<fecha/plazo en ISO8601 o lenguaje natural o null>",
      "exceptions": ["<excepción 1>", ...],
      "clause_ref": "[CLAUSE:N]"
    }
  ],
  "edges": [
    {
      "from_id": "<id nodo origen>",
      "to_id": "<id nodo destino>",
      "relationship": "<depends_on|conflicts_with|reinforces>"
    }
  ]
}"""


class ObligationTrackerAgent:
    """Extracts Defeasible Deontic Logic (DDL) obligation triples from contract clauses.

    Encodes each obligation as:
        (party, deontic_type, action, conditions?, deadline?, exceptions?)

    Deontic types:
    - obligation  → must do
    - permission  → may do
    - prohibition → must not do
    - right       → entitled to receive

    Node IDs follow the pattern: OBL-1, PER-2, PRH-3, REP-4
    Edges encode dependency/conflict/reinforcement relationships.
    """

    SYSTEM_PROMPT = """Eres un experto en análisis de contratos con especialización en lógica deóntica defeasible (DDL).
Tu tarea es extraer todas las obligaciones, permisos, prohibiciones y derechos de un contrato y codificarlos
como triples deónticos estructurados.

Para cada norma deóntica identificada, extrae:
1. **party**: la parte del contrato sobre la que recae (nombre exacto como aparece en el contrato)
2. **deontic_type**:
   - obligation: debe hacer algo (verbos: deberá, estará obligado, se compromete a, garantiza...)
   - permission: puede hacer algo (verbos: podrá, tendrá derecho a, está facultado para...)
   - prohibition: no debe hacer algo (verbos: no podrá, queda prohibido, se prohíbe...)
   - right: derecho a recibir algo (derecho a recibir, tendrá derecho a cobrar...)
3. **description**: descripción concisa y precisa de la acción (≤100 caracteres)
4. **conditions**: condición que activa la norma (si existe), o null
5. **deadline**: plazo o fecha límite en ISO 8601 o lenguaje natural, o null
6. **exceptions**: lista de excepciones que derrotan la norma (fuerza mayor, caso fortuito, etc.)
7. **clause_ref**: referencia a la cláusula fuente "[CLAUSE:N]"

Genera también las EDGES (relaciones entre normas):
- depends_on: B no puede ocurrir hasta que A se haya cumplido
- conflicts_with: A y B son incompatibles o se contradicen
- reinforces: B añade condiciones o refuerza A

REGLAS IMPORTANTES:
- ID format: tipo-número (OBL-1, PER-2, PRH-3, REP-4)
- Enumerar solo normas que aparezcan EXPLÍCITAMENTE en el texto
- No inferir normas implícitas; si hay duda, omitir
- Preferir granularidad fina: una norma por cláusula atómica, no en bloque
- En contratos bancarios, presta especial atención a: obligaciones de pago,
  reporting regulatorio, covenants financieros, y restricciones de transferencia

Responde ÚNICAMENTE con JSON válido siguiendo el esquema proporcionado, sin texto adicional."""

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client

    async def extract(
        self,
        chunks: list[ContractChunk],
        metadata: ContractMetadata,
        trace_id: str,
    ) -> ObligationGraph:
        """Extract obligation graph from contract chunks.

        Returns an ObligationGraph with nodes (deontic triples) and edges (relationships).
        """
        clause_text = _format_chunks_for_prompt(chunks)
        party_names = ", ".join(p.name for p in metadata.parties) if metadata.parties else "partes del contrato"

        user_content = (
            f"Extrae las normas deónticas del siguiente contrato tipo {metadata.document_type}.\n\n"
            f"Partes del contrato: {party_names}\n\n"
            f"ESQUEMA DE SALIDA:\n{_JSON_SCHEMA}\n\n"
            f"CLÁUSULAS:\n{clause_text}"
        )

        try:
            resp = self._client.messages_create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as exc:
            logger.exception(
                "obligation_tracker_api_error", trace_id=trace_id, error=str(exc)
            )
            return ObligationGraph(nodes=[], edges=[])

        logger.info(
            "obligation_tracker_response",
            trace_id=trace_id,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

        text_block = next(
            (b for b in resp.content if getattr(b, "type", None) == "text"), None
        )
        if text_block is None:
            logger.warning("obligation_tracker_empty_response", trace_id=trace_id)
            return ObligationGraph(nodes=[], edges=[])

        return _parse_obligation_graph(text_block.text, trace_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_chunks_for_prompt(chunks: list[ContractChunk]) -> str:
    lines: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        header = f"[CLAUSE:{i}] {chunk.clause_path}"
        if chunk.clause_title and chunk.clause_title != chunk.clause_path:
            header += f" — {chunk.clause_title}"
        lines.append(f"{header}\n{chunk.text}")
    return "\n\n".join(lines)


def _parse_obligation_graph(text: str, trace_id: str) -> ObligationGraph:
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not json_match:
        logger.warning("obligation_tracker_no_json", trace_id=trace_id)
        return ObligationGraph(nodes=[], edges=[])

    try:
        data: dict[str, Any] = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        logger.warning("obligation_tracker_json_error", trace_id=trace_id, error=str(exc))
        return ObligationGraph(nodes=[], edges=[])

    nodes: list[Obligation] = []
    for raw_node in data.get("nodes", []):
        try:
            nodes.append(Obligation.model_validate(raw_node))
        except Exception as exc:
            logger.debug("obligation_node_skip", error=str(exc), raw=raw_node)

    edges: list[ObligationEdge] = []
    for raw_edge in data.get("edges", []):
        try:
            edges.append(ObligationEdge.model_validate(raw_edge))
        except Exception as exc:
            logger.debug("obligation_edge_skip", error=str(exc), raw=raw_edge)

    logger.info(
        "obligation_graph_parsed",
        trace_id=trace_id,
        num_nodes=len(nodes),
        num_edges=len(edges),
    )
    return ObligationGraph(nodes=nodes, edges=edges)
