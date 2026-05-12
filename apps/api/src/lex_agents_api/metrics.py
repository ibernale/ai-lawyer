"""Prometheus metrics for the lex-agents API.

Counters and histograms are registered lazily on first import.
Record after each successful consult response in the endpoint handler.
"""

from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, Histogram
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

if _PROMETHEUS_AVAILABLE:
    QUERY_DEPTH = Counter(
        "legal_query_depth_total",
        "Total queries by processing depth",
        ["depth"],
    )
    QUERY_BRANCH = Counter(
        "legal_query_branch_total",
        "Total queries by primary branch",
        ["branch"],
    )
    QUERY_COST = Histogram(
        "legal_query_cost_usd",
        "Query cost in USD by primary branch",
        ["branch"],
        buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    )

    # Document agents
    DOCUMENTS_PROCESSED = Counter(
        "documents_processed_total",
        "Documents processed by format",
        ["format"],  # pdf, docx, txt, eml
    )
    DOCUMENT_ANALYSIS_LATENCY = Histogram(
        "document_analysis_latency_seconds",
        "Document analysis latency in seconds",
        ["mode"],
        buckets=[1, 2, 5, 10, 30, 60, 120],
    )

    # Comparative law
    COMPARATIVE_LAW_INVOCATIONS = Counter(
        "comparative_law_invocations_total",
        "Comparative law analyses by jurisdiction pair",
        ["jurisdiction_pair"],  # e.g. "ES-EU", "ES-EU-BR"
    )

    # Audit & feedback
    AUDIT_SAMPLES_PENDING = Gauge(
        "audit_samples_pending",
        "Number of audit samples awaiting review",
    )
    AUDIT_SAMPLES_REVIEWED = Counter(
        "audit_samples_reviewed_total",
        "Audit samples reviewed, by verdict",
        ["verdict"],  # correcto, dudoso, incorrecto
    )
    USER_FEEDBACK = Counter(
        "user_feedback_total",
        "User feedback verdicts",
        ["verdict"],  # aceptable, dudoso, incorrecto
    )

    # Unsupported queries
    UNSUPPORTED_QUERIES = Counter(
        "unsupported_queries_total",
        "Queries rejected by unsupported_detector, by pattern",
        ["pattern"],  # cuantificacion, estrategia, plazo_activo, asesoramiento_personal
    )

    # Strict citation rejections
    STRICT_CITATION_REJECTIONS = Counter(
        "strict_citation_rejections_total",
        "Responses blocked by strict citation verifier",
        ["branch"],
    )

    # FinOps cost tracking (ADR 0031)
    COST_ESTIMATE_HOURLY = Gauge(
        "cost_estimate_hourly_usd",
        "Estimated cost accumulated in the current hour",
        ["agent", "model"],
    )
    COST_RECONCILIATION_DRIFT = Gauge(
        "cost_reconciliation_drift_pct",
        "Absolute drift % from the last daily reconciliation run",
    )


def record_query(depth: str, branch: str, cost_usd: float) -> None:
    """Record depth, branch, and cost metrics for a completed query."""
    if not _PROMETHEUS_AVAILABLE:
        return
    QUERY_DEPTH.labels(depth=depth).inc()
    QUERY_BRANCH.labels(branch=branch).inc()
    QUERY_COST.labels(branch=branch).observe(cost_usd)


def record_document_processed(format: str) -> None:
    """Increment the documents processed counter for the given format."""
    if not _PROMETHEUS_AVAILABLE:
        return
    DOCUMENTS_PROCESSED.labels(format=format).inc()


def record_document_analysis(mode: str, latency_seconds: float) -> None:
    """Record document analysis latency for the given mode."""
    if not _PROMETHEUS_AVAILABLE:
        return
    DOCUMENT_ANALYSIS_LATENCY.labels(mode=mode).observe(latency_seconds)


def record_comparative_invocation(jurisdictions: list[str]) -> None:
    """Record a comparative law invocation for the given list of jurisdictions."""
    if not _PROMETHEUS_AVAILABLE:
        return
    jurisdiction_pair = "-".join(sorted(jurisdictions))
    COMPARATIVE_LAW_INVOCATIONS.labels(jurisdiction_pair=jurisdiction_pair).inc()


def record_audit_pending(count: int) -> None:
    """Set the gauge for audit samples awaiting review."""
    if not _PROMETHEUS_AVAILABLE:
        return
    AUDIT_SAMPLES_PENDING.set(count)


def record_audit_reviewed(verdict: str) -> None:
    """Increment the audit samples reviewed counter for the given verdict."""
    if not _PROMETHEUS_AVAILABLE:
        return
    AUDIT_SAMPLES_REVIEWED.labels(verdict=verdict).inc()


def record_user_feedback(verdict: str) -> None:
    """Increment the user feedback counter for the given verdict."""
    if not _PROMETHEUS_AVAILABLE:
        return
    USER_FEEDBACK.labels(verdict=verdict).inc()


def record_unsupported_query(pattern: str) -> None:
    """Increment the unsupported queries counter for the given pattern."""
    if not _PROMETHEUS_AVAILABLE:
        return
    UNSUPPORTED_QUERIES.labels(pattern=pattern).inc()


def record_strict_citation_rejection(branch: str) -> None:
    """Increment the strict citation rejections counter for the given branch."""
    if not _PROMETHEUS_AVAILABLE:
        return
    STRICT_CITATION_REJECTIONS.labels(branch=branch).inc()
