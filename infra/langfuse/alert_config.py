# ruff: noqa: T201
"""
Langfuse alert configuration for lex-agents.

Run this script once after Langfuse is integrated (Fase 9) to register
alert rules via the Langfuse API.

Requires env vars:
  LANGFUSE_SECRET_KEY  — project secret key from Langfuse settings
  LANGFUSE_HOST        — base URL of the Langfuse instance (default: localhost:3003)

Usage:
  python infra/langfuse/alert_config.py          # dry-run (no API calls)
  LANGFUSE_SECRET_KEY=sk-... python infra/langfuse/alert_config.py

Note: All API calls are commented out until Langfuse is integrated in Fase 9.
"""

import os

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://localhost:3003")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")

# ---------------------------------------------------------------------------
# Alert rule definitions
# ---------------------------------------------------------------------------

ALERT_RULES = [
    {
        "name": "hallucination_score_low",
        "description": (
            "Fires when the 'hallucination' evaluator score drops below 0.7 "
            "in more than 5 traces within a rolling 1-hour window. "
            "Indicates that the model may be generating unsupported legal claims."
        ),
        "severity": "critical",
        "condition": {
            "type": "score_threshold",
            "score_name": "hallucination",
            "operator": "lt",
            "threshold": 0.7,
            "aggregation": "count_below_threshold",
            "window": "1h",
            "min_count": 5,
        },
        "notification_channel": "webhook",
    },
    {
        "name": "verification_red_rate",
        "description": (
            "Fires when the custom 'verification_status' score equals 'red' "
            "in more than 10% of traces within a rolling 1-hour window. "
            "Indicates that citation verification is failing at an elevated rate."
        ),
        "severity": "warning",
        "condition": {
            "type": "score_ratio",
            "score_name": "verification_status",
            "value": "red",
            "operator": "gt",
            "threshold": 0.10,
            "window": "1h",
        },
        "notification_channel": "webhook",
    },
    {
        "name": "trace_cost_runaway",
        "description": (
            "Fires when a single trace's usage.totalCost exceeds $0.50 USD. "
            "Catches runaway agentic loops or unexpectedly large context windows "
            "before they accumulate significant cost."
        ),
        "severity": "critical",
        "condition": {
            "type": "usage_threshold",
            "metric": "usage.totalCost",
            "operator": "gt",
            "threshold": 0.50,
            "unit": "USD",
            "per": "trace",
        },
        "notification_channel": "webhook",
    },
    {
        "name": "evaluator_failure",
        "description": (
            "Fires when any configured evaluator returns an HTTP error or raises "
            "an exception during execution. Ensures that silent evaluator failures "
            "do not go undetected and leave traces unscored."
        ),
        "severity": "warning",
        "condition": {
            "type": "evaluator_error",
            "match": "any",
            "error_types": ["http_error", "exception"],
        },
        "notification_channel": "webhook",
    },
]

# ---------------------------------------------------------------------------
# Configuration function
# ---------------------------------------------------------------------------


def configure_alerts() -> None:
    """Register alert rules with the Langfuse API (dry-run until Fase 9)."""

    print("Langfuse alert config (dry-run):")
    print(f"  Host:  {LANGFUSE_HOST}")
    print(f"  Auth:  {'SET' if LANGFUSE_SECRET_KEY else 'NOT SET (dry-run only)'}")
    print()

    for rule in ALERT_RULES:
        print(f"  - {rule['name']} [{rule['severity']}]: {rule['description']}")

    # TODO: invoke when LANGFUSE_SECRET_KEY is set
    #
    # import base64
    # import json
    # import urllib.request
    #
    # credentials = base64.b64encode(
    #     f":{LANGFUSE_SECRET_KEY}".encode()
    # ).decode()
    # headers = {
    #     "Authorization": f"Basic {credentials}",
    #     "Content-Type": "application/json",
    # }
    #
    # for rule in ALERT_RULES:
    #     payload = json.dumps(rule).encode()
    #     req = urllib.request.Request(
    #         f"{LANGFUSE_HOST}/api/public/alerts",
    #         data=payload,
    #         headers=headers,
    #         method="POST",
    #     )
    #     try:
    #         with urllib.request.urlopen(req) as response:
    #             body = json.loads(response.read())
    #             print(f"  [OK] {rule['name']} registered: id={body.get('id')}")
    #     except urllib.error.HTTPError as exc:
    #         print(f"  [ERR] {rule['name']} failed: HTTP {exc.code} — {exc.reason}")
    #     except urllib.error.URLError as exc:
    #         print(f"  [ERR] {rule['name']} failed: {exc.reason}")


if __name__ == "__main__":
    configure_alerts()
