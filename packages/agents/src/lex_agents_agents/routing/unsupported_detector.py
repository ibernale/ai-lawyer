"""Detector for query patterns that fall outside the system's supported scope.

Detects 4 categories of unsupported queries using regex patterns:
  - cuantificacion: requests for specific monetary/time quantification of penalties
  - estrategia: requests for litigation/procedural strategy
  - plazo_activo: active procedural deadlines with a specific date
  - asesoramiento_personal: personal specific legal advice ("¿debo firmar?")

Returns a DegradedResponse when a pattern matches, so the orchestrator can
short-circuit before RAG and LLM calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: list[tuple[str, str]] = [
    # cuantificacion: specific monetary/sanction amounts
    (
        "cuantificacion",
        r"(?i)\b("
        r"cu[aá]nto\s+(es|ser[aá]|vale|cuesta|cobran?|multan?|pagar?|sancionan?)"
        r"|importe\s+(exact[oa]|concreto|preciso)"
        r"|cu[aá]nto\s+tengo\s+que\s+pagar"
        r"|cu[aá]l\s+es\s+la\s+multa"
        r"|cu[aá]nto\s+(me|nos)\s+(cobrar[aá][nt]?|multar[aá][nt]?|impondr[aá][nt]?)"
        r")\b",
    ),
    # estrategia: litigation / procedural strategy
    (
        "estrategia",
        r"(?i)\b("
        r"(c[oó]mo|qu[eé])\s+(defender|recurrir|impugnar|alegar|plantear\s+la\s+defensa)"
        r"|estrategia\s+(procesal|de\s+defensa|judicial|de\s+litigaci[oó]n)"
        r"|c[oó]mo\s+(ganar|evitar\s+(que\s+)?me\s+(condenen?|sancionen?|embarguen?))"
        r"|qu[eé]\s+(alegaciones?|recursos?|escritos?)\s+(presentar|interponer|formular)"
        r")\b",
    ),
    # plazo_activo: active procedural deadlines with a specific date
    (
        "plazo_activo",
        r"(?i)\b("
        r"tengo\s+(hasta|de\s+plazo\s+hasta)"
        r"|me\s+queda[n]?\s+(solo\s+)?\d+\s+d[ií]as?"
        r"|el\s+plazo\s+(vence|termina|expira)\s+el"
        r"|urge(nte)?[,.]?\s+(mi\s+)?plazo"
        r"|plazo\s+de\s+recurso\s+(es|son)\s+\d+"
        r")\b",
    ),
    # asesoramiento_personal: direct personal advice
    (
        "asesoramiento_personal",
        r"(?i)\b("
        r"(debo|tengo\s+que|debería|me\s+(recomiendas?|aconsejas?))\s+"
        r"(firmar|aceptar|rechazar|demandar|denunciar|recurrir|pagar|negociar)"
        r"|qu[eé]\s+(hago|hago|haría\s+yo|me\s+recomiendas?)\s+(ahora|en\s+mi\s+caso)"
        r"|(firma|acepta|rechaza|demanda)\s+(o\s+no|esto)"
        r"|es\s+mejor\s+para\s+m[ií]\s+(aceptar|rechazar|firmar|demandar)"
        r")\b",
    ),
]

_COMPILED: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pattern)) for name, pattern in _PATTERNS
]

_DEGRADED_TEMPLATE = (
    "Esta consulta requiere asesoramiento jurídico cualificado. "
    "El sistema lex-agents solo proporciona contexto normativo general sobre regulación "
    "bancaria, protección de datos, derecho laboral, mercantil, penal económico y "
    "derecho administrativo. No puede {reason}.\n\n"
    "Para su consulta específica, le recomendamos contactar con los servicios "
    "jurídicos especializados correspondientes."
)

_REASON_BY_PATTERN = {
    "cuantificacion": "calcular importes exactos de multas o sanciones — estos dependen del caso concreto y son determinados por la autoridad competente",
    "estrategia": "diseñar estrategias procesales o de defensa — esto requiere análisis individualizado por un abogado",
    "plazo_activo": "gestionar plazos procesales activos — si tiene un plazo inminente, acuda urgentemente a un profesional jurídico",
    "asesoramiento_personal": "dar asesoramiento jurídico personal sobre qué decisión tomar en su caso concreto",
}


@dataclass
class DetectionResult:
    detected: bool
    pattern: str | None = None
    degraded_response: str | None = None


def detect_unsupported(query: str) -> DetectionResult:
    """Return DetectionResult with detected=True and a degraded response if query matches."""
    for pattern_name, compiled in _COMPILED:
        if compiled.search(query):
            reason = _REASON_BY_PATTERN[pattern_name]
            response = _DEGRADED_TEMPLATE.format(reason=reason)
            return DetectionResult(
                detected=True,
                pattern=pattern_name,
                degraded_response=response,
            )
    return DetectionResult(detected=False)
