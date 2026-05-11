"""Prometheus metrics for the lex-agents API.

Counters and histograms are registered lazily on first import.
Record after each successful consult response in the endpoint handler.
"""

from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram
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


def record_query(depth: str, branch: str, cost_usd: float) -> None:
    """Record depth, branch, and cost metrics for a completed query."""
    if not _PROMETHEUS_AVAILABLE:
        return
    QUERY_DEPTH.labels(depth=depth).inc()
    QUERY_BRANCH.labels(branch=branch).inc()
    QUERY_COST.labels(branch=branch).observe(cost_usd)
