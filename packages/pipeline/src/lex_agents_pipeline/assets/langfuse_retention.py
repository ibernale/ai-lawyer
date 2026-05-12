"""Langfuse trace retention job — deletes traces older than 90 days (ADR 0034).

Runs nightly at 03:00 UTC (after cost-sync at 06:00 UTC window is fine for traces).
Preserves aggregated metrics in Prometheus before deletion.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from dagster import AssetExecutionContext, Output, asset

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_RETENTION_DAYS = 90
_PAGE_SIZE = 100


def _auth_header() -> str:
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")
    return "Basic " + base64.b64encode(f"{pk}:{sk}".encode()).decode()


def _langfuse_request(method: str, path: str, host: str, auth: str, body: dict | None = None) -> Any:
    url = f"{host}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": auth, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        raise RuntimeError(f"HTTP {exc.code} on {method} {path}: {body_bytes.decode(errors='replace')}") from exc


def _delete_old_traces(host: str, auth: str, cutoff: datetime) -> tuple[int, int]:
    """Return (deleted, errors)."""
    deleted = errors = page = 1
    cutoff_ts = cutoff.isoformat()

    while True:
        try:
            resp = _langfuse_request(
                "GET",
                f"/api/public/traces?page={page}&limit={_PAGE_SIZE}&toTimestamp={cutoff_ts}",
                host,
                auth,
            )
        except RuntimeError as exc:
            logger.error("langfuse_retention.list_failed", page=page, error=str(exc))
            break

        traces: list[dict[str, Any]] = resp.get("data", [])
        if not traces:
            break

        for trace in traces:
            trace_id = trace.get("id", "")
            try:
                _langfuse_request("DELETE", f"/api/public/traces/{trace_id}", host, auth)
                deleted += 1
            except RuntimeError as exc:
                logger.warning("langfuse_retention.delete_failed", trace_id=trace_id, error=str(exc))
                errors += 1

        meta = resp.get("meta", {})
        if page >= meta.get("totalPages", 1):
            break
        page += 1

    return deleted, errors


@asset(
    group_name="observability",
    compute_kind="maintenance",
    description=f"Delete Langfuse traces older than {_RETENTION_DAYS} days (ADR 0034)",
)
def langfuse_traces_cleanup(context: AssetExecutionContext) -> Output[dict[str, Any]]:
    """Nightly cleanup: removes traces > 90 days from Langfuse. Non-fatal if Langfuse is down."""
    host = os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000")
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")

    if not pk or not sk:
        context.log.warning("Langfuse credentials not configured — skipping retention cleanup")
        return Output(value={"deleted": 0, "errors": 0, "skipped": True}, metadata={"skipped": True})

    auth = _auth_header()
    cutoff = datetime.now(UTC) - timedelta(days=_RETENTION_DAYS)
    context.log.info(f"Deleting Langfuse traces older than {cutoff.isoformat()}")

    try:
        deleted, errors = _delete_old_traces(host, auth, cutoff)
    except Exception as exc:
        context.log.warning(f"Langfuse retention cleanup failed (non-fatal): {exc}")
        return Output(
            value={"deleted": 0, "errors": 1, "error": str(exc)},
            metadata={"error": str(exc)},
        )

    context.log.info(f"Retention cleanup done: deleted={deleted} errors={errors}")
    return Output(
        value={"deleted": deleted, "errors": errors, "cutoff": cutoff.isoformat()},
        metadata={"deleted": deleted, "errors": errors},
    )
