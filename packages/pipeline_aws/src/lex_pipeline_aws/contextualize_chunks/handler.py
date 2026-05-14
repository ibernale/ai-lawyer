"""ContextualizeChunks Lambda handler."""
from __future__ import annotations

from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return {**event, "status": "contextualized"}
