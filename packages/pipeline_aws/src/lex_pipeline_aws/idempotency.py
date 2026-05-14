"""DynamoDB-backed idempotency guard for pipeline stages (ADR 0047).

Each Lambda stage checks DynamoDB before doing work:
  - If ``doc_id`` is already in state ``success`` → return cached result
  - If ``doc_id`` is in state ``running`` → return 409 (Step Functions retries)
  - Otherwise → set state to ``running``, do work, set state to ``success``

TTL: 7 days (stages are idempotent within a weekly window).
"""

from __future__ import annotations

import os
import time
from typing import Any

import boto3
import structlog
from botocore.exceptions import ClientError

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_TABLE_NAME = os.environ.get(
    "IDEMPOTENCY_TABLE",
    "lex-agents-dev-pipeline-idempotency",
)
_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def _table():  # type: ignore[return]
    return boto3.resource("dynamodb").Table(_TABLE_NAME)


class AlreadySucceeded(Exception):
    """Raised when the stage has already run successfully for this doc_id."""
    def __init__(self, cached_output: dict[str, Any]) -> None:
        self.cached_output = cached_output
        super().__init__(f"Stage already succeeded for doc_id={cached_output.get('doc_id')}")


class StillRunning(Exception):
    """Raised when another execution is currently processing this doc_id."""


def acquire_lock(doc_id: str, stage: str) -> None:
    """Try to set the stage state to 'running'.

    Raises:
        AlreadySucceeded: if the stage already completed successfully.
        StillRunning: if another execution is running (Step Functions will retry).
        botocore.exceptions.ClientError: on DynamoDB errors.
    """
    key = f"{stage}#{doc_id}"
    expires_at = int(time.time()) + _TTL_SECONDS
    try:
        _table().put_item(
            Item={
                "doc_id": key,
                "stage": stage,
                "status": "running",
                "expires_at": expires_at,
            },
            ConditionExpression="attribute_not_exists(doc_id) OR #s = :failed",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":failed": "failed"},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Item exists and is not in "failed" state — check if success or running
            existing = _table().get_item(Key={"doc_id": key}).get("Item", {})
            if existing.get("status") == "success":
                raise AlreadySucceeded(existing.get("cached_output", {})) from exc
            raise StillRunning(f"Stage {stage} is still running for doc_id={doc_id}") from exc
        raise


def release_lock(doc_id: str, stage: str, output: dict[str, Any]) -> None:
    """Mark the stage as successfully completed and cache the output."""
    key = f"{stage}#{doc_id}"
    expires_at = int(time.time()) + _TTL_SECONDS
    _table().put_item(Item={
        "doc_id": key,
        "stage": stage,
        "status": "success",
        "cached_output": output,
        "expires_at": expires_at,
    })
    logger.info("stage_completed", stage=stage, doc_id=doc_id)


def fail_lock(doc_id: str, stage: str, error: str) -> None:
    """Mark the stage as failed so the next retry can re-run it."""
    key = f"{stage}#{doc_id}"
    expires_at = int(time.time()) + _TTL_SECONDS
    _table().put_item(Item={
        "doc_id": key,
        "stage": stage,
        "status": "failed",
        "error": error,
        "expires_at": expires_at,
    })
    logger.warning("stage_failed", stage=stage, doc_id=doc_id, error=error)
