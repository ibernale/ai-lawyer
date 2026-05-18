"""LLM-as-judge metrics for lex-agents using DeepEval GEval.

All metrics are OPTIONAL — callers must explicitly enable them via ``--geval``.
Failures are silenced and reported as ``-1.0`` to avoid blocking the eval pipeline
when DeepEval is unavailable (rate limits, missing API key, etc.).

DeepEval defaults to OpenAI as judge.  We provide ``_AnthropicDeepEvalModel``
to route evaluation calls through the project's own ``AnthropicClientWrapper``
with ``MODEL_HAIKU`` (cheapest option, sufficient for binary judgements).
"""

from __future__ import annotations

import os
from typing import Any

import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Anthropic model wrapper for DeepEval
# ---------------------------------------------------------------------------

def _build_anthropic_model(api_key: str) -> Any:
    """Return a DeepEvalBaseLLM instance backed by Claude Haiku."""
    from deepeval.models import DeepEvalBaseLLM
    from lex_agents_shared.anthropic_client import MODEL_HAIKU, AnthropicClientWrapper

    class _AnthropicDeepEvalModel(DeepEvalBaseLLM):
        """Minimal DeepEvalBaseLLM wrapper that delegates to AnthropicClientWrapper."""

        def __init__(self, api_key: str) -> None:
            self._wrapper = AnthropicClientWrapper(api_key=api_key)
            self._model_name = MODEL_HAIKU

        # DeepEval requires both sync and async implementations.
        def generate(self, prompt: str) -> str:  # type: ignore[override]
            response = self._wrapper.messages_create(
                model=self._model_name,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content
            if content and hasattr(content[0], "text"):
                return content[0].text  # type: ignore[no-any-return]
            return ""

        async def a_generate(self, prompt: str) -> str:  # type: ignore[override]
            # DeepEval calls the async variant when running async test cases.
            # We fall back to the sync path via a thread to avoid a second
            # async client dependency in this module.
            import asyncio

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.generate, prompt)

        def get_model_name(self) -> str:
            return self._model_name

    return _AnthropicDeepEvalModel(api_key=api_key)


# ---------------------------------------------------------------------------
# Custom metric: LegalCitationGrounding
# ---------------------------------------------------------------------------

def _build_citation_grounding_metric(model: Any) -> Any:
    """Build a custom BaseMetric that checks citation backing for normative claims."""
    from deepeval.metrics import BaseMetric
    from deepeval.test_case import LLMTestCase

    class LegalCitationGroundingMetric(BaseMetric):
        """Score 1.0 if all regulatory claims are backed by retrieval context,
        0.5 if partially backed, 0.0 if the answer makes unsupported normative
        claims.

        Threshold: 0.7  (higher is better).
        """

        name = "LegalCitationGrounding"
        threshold: float = 0.7
        is_higher_better: bool = True

        _CRITERION = (
            "Every regulatory claim in the answer has a supporting citation in the "
            "retrieval context. Score 1 if all claims are supported, 0.5 if partially, "
            "0 if the answer makes unsupported normative claims."
        )

        def __init__(self) -> None:
            super().__init__()
            self._model = model

        def measure(self, test_case: LLMTestCase) -> float:  # type: ignore[override]
            retrieval_ctx = test_case.retrieval_context or []
            context_text = "\n\n".join(retrieval_ctx) if retrieval_ctx else "(none)"
            prompt = (
                "You are a legal evaluation expert. Apply the following criterion strictly.\n\n"
                f"CRITERION: {self._CRITERION}\n\n"
                f"ANSWER:\n{test_case.actual_output}\n\n"
                f"RETRIEVAL CONTEXT:\n{context_text}\n\n"
                "Respond with ONLY a single floating-point number: 0.0, 0.5, or 1.0."
            )
            raw = self._model.generate(prompt).strip()
            try:
                score = float(raw.split()[0])
            except (ValueError, IndexError):
                score = 0.0
            self.score = round(max(0.0, min(1.0, score)), 4)
            self.success = self.score >= self.threshold
            return self.score

        async def a_measure(self, test_case: LLMTestCase) -> float:  # type: ignore[override]
            import asyncio

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.measure, test_case)

        def is_successful(self) -> bool:
            return bool(self.success)

    return LegalCitationGroundingMetric()


# ---------------------------------------------------------------------------
# GEval metrics
# ---------------------------------------------------------------------------

def _build_geval_metrics(model: Any) -> tuple[Any, Any]:
    """Return ``(LegalCoherenceGEval, LegalCompletenessGEval)`` instances."""
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    coherence = GEval(
        name="LegalCoherence",
        criteria=(
            "The answer is logically coherent, legally precise, and the citations "
            "[REF:n] appear in appropriate positions to support specific claims. "
            "All regulatory articles cited exist and match the domain "
            "(banking regulation EU/ES)."
        ),
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.INPUT],
        threshold=0.7,
        model=model,
    )

    completeness = GEval(
        name="LegalCompleteness",
        criteria=(
            "The answer fully addresses all aspects of the legal question asked, "
            "covers the relevant regulatory framework (CRR, BRRD, PSD2, RGPD as "
            "applicable), and notes important caveats or exceptions."
        ),
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.INPUT],
        threshold=0.6,
        model=model,
    )

    return coherence, completeness


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_geval(
    answer: str,
    query: str,
    retrieval_context: list[str],
    api_key: str,
) -> dict[str, float]:
    """Run the three GEval metrics and return a score dict.

    Keys: ``citation_grounding``, ``coherence``, ``completeness``.
    Value ``-1.0`` indicates the metric could not be computed (e.g. rate
    limit, missing dependency).

    Args:
        answer: The agent's answer text.
        query: The original legal query sent to the agent.
        retrieval_context: Chunks retrieved and used to build the answer.
        api_key: Anthropic API key — forwarded to ``AnthropicClientWrapper``.

    Returns:
        Mapping of metric name → score in [0, 1], or -1.0 on failure.
    """
    from deepeval.test_case import LLMTestCase

    # Ensure DeepEval does not attempt its own OpenAI calls for the model.
    # We override with our Anthropic wrapper at construction time, but some
    # internals fall back to the env var when the model param is absent.
    os.environ.setdefault("OPENAI_API_KEY", api_key)

    scores: dict[str, float] = {
        "citation_grounding": -1.0,
        "coherence": -1.0,
        "completeness": -1.0,
    }

    try:
        anthropic_model = _build_anthropic_model(api_key)
    except Exception:
        return scores

    test_case = LLMTestCase(
        input=query,
        actual_output=answer,
        retrieval_context=retrieval_context,
    )

    # --- citation grounding (custom metric) ---
    try:
        metric = _build_citation_grounding_metric(anthropic_model)
        metric.measure(test_case)
        scores["citation_grounding"] = float(metric.score)
    except Exception as exc:
        logger.debug("geval_citation_grounding_failed", exc=str(exc))

    # --- coherence (GEval) ---
    completeness_metric = None
    try:
        coherence, completeness_metric = _build_geval_metrics(anthropic_model)
        coherence.measure(test_case)
        scores["coherence"] = float(coherence.score)
    except Exception as exc:
        logger.debug("geval_coherence_failed", exc=str(exc))

    # --- completeness (GEval) ---
    try:
        if completeness_metric is None:
            _, completeness_metric = _build_geval_metrics(anthropic_model)
        completeness_metric.measure(test_case)
        scores["completeness"] = float(completeness_metric.score)
    except Exception as exc:
        logger.debug("geval_completeness_failed", exc=str(exc))

    return scores
