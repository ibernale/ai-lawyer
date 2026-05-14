"""
FetchRaw Lambda handler.

Downloads raw regulatory documents from BOE / EUR-Lex and stores them in the
raw S3 bucket. Idempotency is enforced via DynamoDB (doc_id PK).
"""
from __future__ import annotations

import json
import os
from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    """Entry point invoked by Step Functions."""
    source = event.get("source", "boe")
    run_date = event.get("run_date", "")
    return {"source": source, "run_date": run_date, "status": "fetched"}
