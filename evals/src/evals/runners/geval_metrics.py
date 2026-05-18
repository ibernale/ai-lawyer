"""LLM-as-judge eval metrics using DeepEval GEval (Fase 11B.2).

Provides three complementary metrics:
  - LegalCitationGroundingMetric  custom metric — checks each citation claim
    is actually supported by the retrieved context (threshold 0.7)
  - LegalCoherenceGEval           GEval — legal reasoning is internally consistent
  - LegalCompletenessGEval        GEval — answer addresses all aspects of the query

All LLM judge calls are routed through AnthropicClientWrapper (Claude Haiku)
via _AnthropicDeepEvalModel so no separate API client is needed.

Public entry point::

    scores = run_geval(answer, query, retrieval_context, api_key="sk-ant-...")
    # Returns e.g. {"citation_grounding": 0.8, "coherence": 0.9, "completeness": 0.7}
    # Returns {metric: -1.0} for any metric that fails (safe to skip in aggregation)

Import cost: ``deepeval`` is lazily imported inside run_geval() so loading this
module does NOT pull in the DeepEval dependency unless the flag is active.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from lex_agents_shared.anthropic_client import AnthropicClientWrapper

logger: structlog.BoundLogger = structlog.get_logger(__name__)


def run_geval(
    answer: str,
    query: str,
    retrieval_context: list[str],
    api_key: str,
) -> dict[str, float]:
    """Run all GEval metrics and return a score dict.

    Values are in [0, 1].  A value of ``-1.0`` means the metric failed
    (API error, parse error, etc.) and should be excluded from averages.

    Lazily imports deepeval so CI stays fast when ``--geval`` is not passed.
    """
    from lex_agents_shared.anthropic_client import MODEL_HAIKU, AnthropicClientWrapper

    client = AnthropicClientWrapper(api_key=api_key)
    scores: dict[str, float] = {}

    # ── LegalCitationGrounding (custom metric) ────────────────────────────────
    try:
        scores["citation_grounding"] = _run_citation_grounding(
            answer, retrieval_context, client
        )
    except Exception:
        logger.debug("geval_citation_grounding_failed")
        scores["citation_grounding"] = -1.0

    # ── GEval metrics via DeepEval ────────────────────────────────────────────
    try:
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, LLMTestCaseParams

        judge_model = _AnthropicDeepEvalModel(client=client, model=MODEL_HAIKU)
        test_case = LLMTestCase(
            input=query,
            actual_output=answer,
            retrieval_context=retrieval_context or [""],
        )

        # Coherence
        coherence_metric = GEval(
            name="LegalCoherence",
            model=judge_model,
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
            ],
            criteria=(
                "El razonamiento jurídico es internamente coherente: "
                "las afirmaciones no se contradicen entre sí, la cadena "
                "argumental es lógica y las conclusiones se derivan de las premisas."
            ),
            threshold=0.6,
        )
        try:
            coherence_metric.measure(test_case)
            scores["coherence"] = float(coherence_metric.score or 0.0)
        except Exception:
            logger.debug("geval_coherence_failed")
            scores["coherence"] = -1.0

        # Completeness
        completeness_metric = GEval(
            name="LegalCompleteness",
            model=judge_model,
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
            ],
            criteria=(
                "La respuesta aborda todos los aspectos relevantes de la consulta: "
                "cubre las jurisdicciones pertinentes, menciona los requisitos "
                "aplicables y no omite elementos materiales del análisis jurídico."
            ),
            threshold=0.6,
        )
        try:
            completeness_metric.measure(test_case)
            scores["completeness"] = float(completeness_metric.score or 0.0)
        except Exception:
            logger.debug("geval_completeness_failed")
            scores["completeness"] = -1.0

    except ImportError:
        logger.warning("deepeval_not_installed_skipping_geval")
        scores.setdefault("coherence", -1.0)
        scores.setdefault("completeness", -1.0)
    except Exception:
        logger.exception("geval_metrics_failed")
        scores.setdefault("coherence", -1.0)
        scores.setdefault("completeness", -1.0)

    return scores


# ---------------------------------------------------------------------------
# Custom citation grounding metric (no DeepEval dependency)
# ---------------------------------------------------------------------------

def _run_citation_grounding(
    answer: str,
    retrieval_context: list[str],
    client: AnthropicClientWrapper,
) -> float:
    """Score citation support: fraction of cited claims backed by retrieved context.

    Uses a single Claude Haiku call with a 0-10 scale; normalises to [0, 1].
    Returns -1.0 on failure.
    """
    from lex_agents_shared.anthropic_client import MODEL_HAIKU  # always available

    if not retrieval_context:
        return -1.0

    context_block = "\n\n".join(f"[{i+1}] {c[:600]}" for i, c in enumerate(retrieval_context[:10]))
    prompt = (
        "Eres un evaluador jurídico. Analiza si las afirmaciones normativas y "
        "jurisprudenciales de la respuesta están respaldadas por el contexto "
        "recuperado.\n\n"
        f"CONSULTA RESPONDIDA:\n{answer[:800]}\n\n"
        f"CONTEXTO RECUPERADO:\n{context_block}\n\n"
        "Puntúa del 0 al 10 el grado en que las citas y afirmaciones de la "
        "respuesta están RESPALDADAS por el contexto anterior. "
        "10 = todas las afirmaciones tienen soporte explícito; "
        "0 = ninguna afirmación tiene soporte.\n\n"
        "Responde ÚNICAMENTE con un número entero entre 0 y 10."
    )
    try:
        resp = client.messages_create(
            model=MODEL_HAIKU,
            max_tokens=16,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (resp.content[0].text or "").strip()
        score = int(raw.split()[0]) / 10.0
        return round(min(max(score, 0.0), 1.0), 3)
    except Exception:
        logger.debug("citation_grounding_parse_failed", raw=locals().get("raw", ""))
        return -1.0


# ---------------------------------------------------------------------------
# DeepEval model adapter for AnthropicClientWrapper
# ---------------------------------------------------------------------------

class _AnthropicDeepEvalModel:
    """Adapter that makes AnthropicClientWrapper look like a DeepEvalBaseLLM.

    Minimal implementation: only ``generate`` and ``get_model_name`` are required
    by GEval.  Async variant not implemented (GEval calls sync ``generate``).
    """

    def __init__(
        self,
        client: AnthropicClientWrapper,
        model: str,
    ) -> None:
        self._client = client
        self._model = model

    # DeepEval interface
    def generate(self, prompt: str) -> str:  # type: ignore[override]
        try:
            resp = self._client.messages_create(
                model=self._model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text if resp.content else ""
        except Exception:
            logger.debug("anthropic_deepeval_model_generate_failed")
            return ""

    async def a_generate(self, prompt: str) -> str:  # type: ignore[override]
        return self.generate(prompt)

    def get_model_name(self) -> str:  # type: ignore[override]
        return self._model

    # Allow GEval to use this object as the ``model=`` parameter directly
    def __repr__(self) -> str:
        return f"_AnthropicDeepEvalModel(model={self._model!r})"
