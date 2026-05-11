"""Backwards-compatibility shim — re-exports from orchestrator_v2."""

from __future__ import annotations

from lex_agents_agents.core.orchestrator_v2 import (
    ConsultRequest,
    ConsultResponse,
    OrchestratorDeps,
    OrchestratorV2 as Orchestrator,
)

__all__ = ["Orchestrator", "ConsultRequest", "ConsultResponse", "OrchestratorDeps"]
