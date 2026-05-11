"""Branch registry — maps branch_id strings to specialist classes."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lex_agents_agents.core.specialist_base import BaseSpecialist

_REGISTRY: dict[str, type["BaseSpecialist"]] = {}


def _build_registry() -> dict[str, type["BaseSpecialist"]]:
    from lex_agents_agents.specialists.regulatorio_bancario_ue_es import (
        RegulatorioBancarioEsAgent,
    )
    from lex_agents_agents.specialists.datos_personales_rgpd import DatosPersonalesRgpdAgent
    from lex_agents_agents.specialists.laboral import LaboralAgent
    from lex_agents_agents.specialists.mercantil_societario import MercantilSocietarioAgent
    from lex_agents_agents.specialists.penal_economico import PenalEconomicoAgent
    from lex_agents_agents.specialists.administrativo import AdministrativoAgent

    return {
        "regulatorio_bancario_ue_es": RegulatorioBancarioEsAgent,
        "datos_personales_rgpd": DatosPersonalesRgpdAgent,
        "laboral": LaboralAgent,
        "mercantil_societario": MercantilSocietarioAgent,
        "penal_economico": PenalEconomicoAgent,
        "administrativo": AdministrativoAgent,
    }


def get_specialist_class(branch_id: str) -> type["BaseSpecialist"]:
    global _REGISTRY
    if not _REGISTRY:
        _REGISTRY = _build_registry()
    cls = _REGISTRY.get(branch_id)
    if cls is None:
        raise ValueError(
            f"Unknown branch '{branch_id}'. "
            f"Available: {sorted(_REGISTRY.keys())}"
        )
    return cls
