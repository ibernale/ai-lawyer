"""ChunkDocument Lambda handler."""
from __future__ import annotations
from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    return {**event, "status": "chunked"}
