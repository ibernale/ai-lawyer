#!/usr/bin/env python3
"""Bootstrap Langfuse after docker-compose up. Used by make langfuse-bootstrap."""
import base64
import os
import sys
import time
import urllib.error
import urllib.request

POLL_INTERVAL = 2  # seconds between health-check attempts
MAX_WAIT = 60  # maximum seconds to wait for Langfuse to become healthy


def wait_for_langfuse(health_url: str) -> bool:
    """Poll the Langfuse health endpoint until healthy or timeout."""
    deadline = time.monotonic() + MAX_WAIT
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            with urllib.request.urlopen(health_url, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        remaining = int(deadline - time.monotonic())
        print(
            f"  [{attempt}] Langfuse not ready yet — waiting {POLL_INTERVAL}s "
            f"(up to {remaining}s remaining)...",
            flush=True,
        )
        time.sleep(POLL_INTERVAL)
    return False


def compute_otlp_basic_auth(pk: str, sk: str) -> str:
    """Return base64(pk:sk) suitable for the Authorization: Basic header."""
    return base64.b64encode(f"{pk}:{sk}".encode()).decode()


def main() -> None:
    port = os.getenv("LANGFUSE_PORT", "3003")
    host = f"http://localhost:{port}"
    health_url = f"{host}/api/public/health"
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")
    email = os.getenv("LANGFUSE_ADMIN_EMAIL", "admin@lex-agents.local")
    password = os.getenv("LANGFUSE_ADMIN_PASSWORD", "changeme-admin-pw")

    print("=" * 60)
    print("  Langfuse bootstrap")
    print("=" * 60)
    print(f"  Health endpoint : {health_url}")
    print(f"  Admin e-mail    : {email}")
    print(f"  Max wait        : {MAX_WAIT}s")
    print()

    print(f"Polling {health_url} ...")
    if not wait_for_langfuse(health_url):
        print(
            f"\nERROR: Langfuse did not become healthy within {MAX_WAIT}s.",
            file=sys.stderr,
        )
        print(
            "  Check container logs with: make langfuse-logs",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\nLangfuse is healthy!")
    print()

    # Compute OTLP basic auth token
    if pk and sk:
        otlp_auth = compute_otlp_basic_auth(pk, sk)
        print("LANGFUSE_OTLP_BASIC_AUTH (add to your .env):")
        print(f"  LANGFUSE_OTLP_BASIC_AUTH={otlp_auth}")
        print()
    else:
        print(
            "WARNING: LANGFUSE_PUBLIC_KEY and/or LANGFUSE_SECRET_KEY not set — "
            "skipping OTLP auth token computation.",
            file=sys.stderr,
        )
        print("  Run 'make langfuse-otlp-auth' after setting those variables.")
        print()

    print("Next steps:")
    print(f"  1. Open   {host}")
    print(f"  2. Log in with  {email}  /  {password}")
    print(
        "  3. Copy the LANGFUSE_OTLP_BASIC_AUTH value above into your .env file."
    )
    print(
        "  4. Restart otel-collector so it picks up the new auth header:"
    )
    print("       docker compose -f infra/docker-compose.yml restart otel-collector")
    print()
    print("Done.")


if __name__ == "__main__":
    main()
