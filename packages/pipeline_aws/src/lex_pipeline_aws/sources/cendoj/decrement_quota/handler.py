"""decrement_quota — decrements CENDOJ quota after successful fetch.

Called as a Step Functions step immediately after a successful CENDOJ document
fetch to atomically increment the daily usage counter in DynamoDB.

Environment variables:
  QUOTA_TABLE : DynamoDB table name for quota tracking
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import boto3

QUOTA_TABLE = os.environ.get("QUOTA_TABLE", "")
dynamodb = boto3.resource("dynamodb")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Decrement (increment used counter) after a successful CENDOJ fetch."""
    table = dynamodb.Table(QUOTA_TABLE)
    today = date.today().isoformat()
    table.update_item(
        Key={"source": "cendoj", "date": today},
        UpdateExpression="ADD used :one",
        ExpressionAttributeValues={":one": 1},
    )
    return event
