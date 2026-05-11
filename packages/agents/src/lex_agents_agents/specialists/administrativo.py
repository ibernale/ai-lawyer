"""Specialist: Spanish administrative law (Maker)."""

from __future__ import annotations

from lex_agents_rag.assembler import AssembledContext

from lex_agents_agents.base_agent import AgentResponse
from lex_agents_agents.core.specialist_base import BaseSpecialist
from lex_agents_agents.shared.definition_of_done import BranchTask


class AdministrativoAgent(BaseSpecialist):
    branch_id = "administrativo"
    prompt_name = "especialistas/administrativo"
    prompt_version = 1

    async def run_async(
        self,
        query: str,
        assembled: AssembledContext,
        trace_id: str,
        sub_task: BranchTask | None = None,
    ) -> AgentResponse:
        effective_query = sub_task.query if sub_task else query
        return self._invoke(effective_query, assembled, trace_id)
