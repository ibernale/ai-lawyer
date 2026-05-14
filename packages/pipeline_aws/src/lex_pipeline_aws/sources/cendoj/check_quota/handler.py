"""check_quota — CENDOJ quota tracker (AMBER source).

Checks the DynamoDB quota table to determine if the daily CENDOJ request
limit has been reached.  Raises an exception if the quota is exhausted,
causing the Step Functions state machine to stop.

Environment variables:
  QUOTA_TABLE         : DynamoDB table name for quota tracking
  CENDOJ_DAILY_QUOTA  : Maximum requests per day (default: 50)
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import boto3

QUOTA_TABLE = os.environ.get("QUOTA_TABLE", "")
DAILY_QUOTA = int(os.environ.get("CENDOJ_DAILY_QUOTA", "50"))
dynamodb = boto3.resource("dynamodb")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Check and atomically reserve one CENDOJ quota slot.

    Uses a conditional UpdateItem (ADD + ConditionExpression) so concurrent
    executions cannot both pass the quota check — the DynamoDB conditional
    write is atomic.  If the quota is already exhausted the condition fails
    and we raise, stopping the state machine.
    """
    from decimal import Decimal

    from botocore.exceptions import ClientError

    table = dynamodb.Table(QUOTA_TABLE)
    today = date.today().isoformat()

    try:
        response = table.update_item(
            Key={"source": "cendoj", "date": today},
            UpdateExpression=(
                "ADD #used :inc "
                "SET #limit = if_not_exists(#limit, :quota_limit)"
            ),
            ConditionExpression=(
                "attribute_not_exists(#used) OR #used < :quota_limit"
            ),
            ExpressionAttributeNames={
                "#used": "used",
                "#limit": "quota_limit",
            },
            ExpressionAttributeValues={
                ":inc": Decimal("1"),
                ":quota_limit": Decimal(str(DAILY_QUOTA)),
            },
            ReturnValues="UPDATED_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise Exception(
                f"CENDOJ daily quota exhausted ({DAILY_QUOTA} requests/day). "
                "State machine will stop. Retry tomorrow or raise CENDOJ_DAILY_QUOTA."
            ) from exc
        raise

    used_after = int(response["Attributes"].get("used", 1))
    return {**event, "quota_remaining": DAILY_QUOTA - used_after, "quota_used": used_after}
