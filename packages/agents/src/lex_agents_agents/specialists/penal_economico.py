"""Specialist: Economic criminal law (Maker).

Always sets verification_partial=True in metadata — this branch is informative only
and must never substitute proper legal defense strategy.
"""

from __future__ import annotations

from lex_agents_rag.assembler import AssembledContext

from lex_agents_agents.base_agent import AgentResponse
from lex_agents_agents.core.specialist_base import BaseSpecialist
from lex_agents_agents.shared.definition_of_done import BranchTask

_PENAL_CAVEAT = (
    "\n\n⚠️ RECORDATORIO: Este análisis es estrictamente informativo. "
    "No constituye ni sustituye la estrategia jurídica de defensa, "
    "que deberá ser elaborada por letrado habilitado en el caso concreto."
)


class PenalEconomicoAgent(BaseSpecialist):
    branch_id = "penal_economico"
    prompt_name = "especialistas/penal_economico"
    prompt_version = 1

    async def run_async(
        self,
        query: str,
        assembled: AssembledContext,
        trace_id: str,
        sub_task: BranchTask | None = None,
    ) -> AgentResponse:
        effective_query = sub_task.query if sub_task else query
        response = self._invoke(
            effective_query, assembled, trace_id, extra_caveat=_PENAL_CAVEAT
        )
        response.answer_text = (
            response.answer_text
            + "\n\n---\n⚠️ **AVISO LEGAL**: Este dictamen es informativo. "
            "No constituye estrategia de defensa jurídica. Consulte letrado habilitado."
        )
        return response
