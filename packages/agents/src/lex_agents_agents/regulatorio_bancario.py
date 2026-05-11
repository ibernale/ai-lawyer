"""Backwards-compatibility shim — re-exports RegulatorioBancarioEsAgent."""

from __future__ import annotations

from lex_agents_agents.specialists.regulatorio_bancario_ue_es import (
    RegulatorioBancarioEsAgent as RegulatorioBancarioAgent,
)

__all__ = ["RegulatorioBancarioAgent"]
