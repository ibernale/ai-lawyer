#!/usr/bin/env python3
"""Push Langfuse evaluator configuration from infra/langfuse-config/evaluators.yaml.

Usage:
    uv run python scripts/langfuse_push_config.py
    make langfuse-push-config

Requires:
    LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
    LANGFUSE_HOST (default: http://localhost:3003)
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml


def _auth_header(pk: str, sk: str) -> str:
    return "Basic " + base64.b64encode(f"{pk}:{sk}".encode()).decode()


def _api(
    method: str,
    path: str,
    body: dict | None,
    host: str,
    auth: str,
) -> dict:
    url = f"{host}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()) if resp.read() else {}
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code} on {method} {path}: {body_text}") from exc


def push_evaluators(config_path: Path, host: str, pk: str, sk: str) -> None:
    auth = _auth_header(pk, sk)
    data = yaml.safe_load(config_path.read_text())
    evaluators = data.get("evaluators", [])

    pushed = skipped = errors = 0

    for ev in evaluators:
        name = ev["name"]
        ev_type = ev.get("type", "model_based")

        # Build payload for Langfuse evaluators API
        payload: dict = {
            "name": name,
            "type": ev_type,
            "sampling": ev.get("sampling", 1.0),
        }
        if "model" in ev:
            payload["model"] = ev["model"]
        if "prompt" in ev:
            payload["prompt"] = ev["prompt"].strip()
        if "output_variable" in ev:
            payload["variable_mapping"] = [{"output_column": "score"}]
        if "description" in ev:
            payload["comment"] = ev["description"]

        try:
            # Try to create; if 409 conflict (already exists) skip
            _api("POST", "/api/public/v2/score-configs", payload, host, auth)
            print(f"  ✓ pushed  {name}")
            pushed += 1
        except RuntimeError as exc:
            if "409" in str(exc) or "already" in str(exc).lower():
                print(f"  · skipped {name} (already exists)")
                skipped += 1
            else:
                print(f"  ✗ error   {name}: {exc}")
                errors += 1

    print(f"\nDone — pushed: {pushed}  skipped: {skipped}  errors: {errors}")
    if errors:
        sys.exit(1)


def main() -> None:
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")
    host = os.getenv("LANGFUSE_HOST", "http://localhost:3003")

    if not pk or not sk:
        print("WARNING: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set — skipping.")
        sys.exit(0)

    config_path = Path(__file__).parent.parent / "infra" / "langfuse-config" / "evaluators.yaml"
    if not config_path.exists():
        print(f"ERROR: config not found at {config_path}")
        sys.exit(1)

    print(f"Pushing evaluator config to {host} ...")
    push_evaluators(config_path, host, pk, sk)


if __name__ == "__main__":
    main()
