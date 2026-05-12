#!/usr/bin/env python3
"""Sync docs/prompts/ with Langfuse Prompt Management.

Usage:
    uv run python scripts/prompts_sync.py --direction push   # git → Langfuse (default)
    uv run python scripts/prompts_sync.py --direction pull   # Langfuse → git
    uv run python scripts/prompts_sync.py --direction both   # bidirectional

Requires: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST env vars.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


# ─── Repo root ────────────────────────────────────────────────────────────────

def _find_repo_root(start: Path) -> Path:
    current = start
    for _ in range(20):
        if (current / "pyproject.toml").exists() and (current / "docs").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise FileNotFoundError(f"Could not locate repo root from {start}")


REPO_ROOT = _find_repo_root(Path(__file__).parent)
PROMPTS_DIR = REPO_ROOT / "docs" / "prompts"


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class LocalPrompt:
    """Parsed local prompt file."""
    name: str           # e.g. "router" or "especialistas/regulatorio_bancario_ue_es"
    version: int
    model: str
    temperature: float
    max_tokens: int
    owner: str
    body: str
    content_hash: str
    source_path: Path

    @property
    def langfuse_name(self) -> str:
        """Name used in Langfuse: <name>_v<version>."""
        safe = self.name.replace("/", "__")
        return f"{safe}_v{self.version}"


# ─── File parsing ─────────────────────────────────────────────────────────────

def _parse_prompt_file(path: Path) -> LocalPrompt | None:
    """Parse a .md prompt file. Returns None if malformed."""
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return None

    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None

    if not isinstance(fm, dict):
        return None

    # Require minimum fields
    required = {"name", "version", "model", "temperature", "max_tokens"}
    if not required.issubset(fm.keys()):
        return None

    body = parts[2].strip()
    content_hash = hashlib.sha256(body.encode()).hexdigest()

    return LocalPrompt(
        name=str(fm["name"]),
        version=int(fm["version"]),
        model=str(fm["model"]),
        temperature=float(fm["temperature"]),
        max_tokens=int(fm["max_tokens"]),
        owner=str(fm.get("owner", "")),
        body=body,
        content_hash=content_hash,
        source_path=path,
    )


def collect_local_prompts() -> list[LocalPrompt]:
    """Recursively collect all parseable .md prompt files under docs/prompts/."""
    prompts: list[LocalPrompt] = []
    for path in sorted(PROMPTS_DIR.rglob("*.md")):
        # Skip README and files inside tests/ subdirectories
        if path.name == "README.md":
            continue
        if "tests" in path.parts:
            continue
        parsed = _parse_prompt_file(path)
        if parsed is not None:
            prompts.append(parsed)
    return prompts


# ─── Langfuse HTTP client ─────────────────────────────────────────────────────

class LangfuseClient:
    """Minimal HTTP client for Langfuse Prompt Management API."""

    def __init__(self, public_key: str, secret_key: str, host: str) -> None:
        self._host = host.rstrip("/")
        token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        self._auth_header = f"Basic {token}"

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._host}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": self._auth_header,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    def push_prompt(self, prompt: LocalPrompt) -> dict[str, Any]:
        """Create or update a prompt in Langfuse."""
        payload: dict[str, Any] = {
            "name": prompt.langfuse_name,
            "type": "text",
            "prompt": prompt.body,
            "labels": ["production"],
            "config": {
                "model": prompt.model,
                "temperature": prompt.temperature,
                "max_tokens": prompt.max_tokens,
            },
        }
        return self._request("POST", "/api/public/v2/prompts", payload)

    def list_prompts(self, page: int = 1, limit: int = 100) -> dict[str, Any]:
        """List prompts from Langfuse."""
        path = f"/api/public/v2/prompts?page={page}&limit={limit}"
        return self._request("GET", path)

    def get_prompt(self, name: str, label: str = "production") -> dict[str, Any]:
        """Fetch a single prompt by name and label."""
        path = f"/api/public/v2/prompts/{urllib.request.quote(name)}?label={label}"
        return self._request("GET", path)


# ─── Push ─────────────────────────────────────────────────────────────────────

def push(client: LangfuseClient, prompts: list[LocalPrompt]) -> tuple[int, int, int]:
    """Push local prompts to Langfuse. Returns (pushed, skipped, errors)."""
    pushed = skipped = errors = 0
    for prompt in prompts:
        try:
            # Try to fetch existing to compare
            try:
                existing = client.get_prompt(prompt.langfuse_name)
                remote_body = existing.get("prompt", "")
                if remote_body == prompt.body:
                    print(f"  SKIP  {prompt.langfuse_name}  (no changes)")
                    skipped += 1
                    continue
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise

            client.push_prompt(prompt)
            print(f"  PUSH  {prompt.langfuse_name}")
            pushed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERR   {prompt.langfuse_name}: {exc}")
            errors += 1
    return pushed, skipped, errors


# ─── Pull ─────────────────────────────────────────────────────────────────────

def _parse_langfuse_name(langfuse_name: str) -> tuple[str, int] | None:
    """Parse 'foo__bar_v2' back to ('foo/bar', 2). Returns None if unrecognised."""
    if "_v" not in langfuse_name:
        return None
    base, _, ver_str = langfuse_name.rpartition("_v")
    try:
        version = int(ver_str)
    except ValueError:
        return None
    name = base.replace("__", "/")
    return name, version


def pull(client: LangfuseClient) -> tuple[int, int, int]:
    """Pull prompts from Langfuse and write to docs/prompts/. Returns (pulled, skipped, errors)."""
    pulled = skipped = errors = 0
    page = 1
    while True:
        try:
            data = client.list_prompts(page=page)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERR   listing prompts (page {page}): {exc}")
            errors += 1
            break

        items = data.get("data", [])
        if not items:
            break

        for item in items:
            langfuse_name: str = item.get("name", "")
            parsed = _parse_langfuse_name(langfuse_name)
            if parsed is None:
                print(f"  SKIP  {langfuse_name}  (unrecognised name format)")
                skipped += 1
                continue

            name, version = parsed
            target_path = PROMPTS_DIR / name / f"v{version}.md"

            # Fetch full prompt content
            try:
                full = client.get_prompt(langfuse_name)
            except Exception as exc:  # noqa: BLE001
                print(f"  ERR   {langfuse_name}: {exc}")
                errors += 1
                continue

            remote_body: str = full.get("prompt", "")
            config: dict[str, Any] = full.get("config", {})

            # Check if local file already matches
            if target_path.exists():
                local_parsed = _parse_prompt_file(target_path)
                if local_parsed is not None:
                    local_hash = hashlib.sha256(local_parsed.body.encode()).hexdigest()
                    remote_hash = hashlib.sha256(remote_body.encode()).hexdigest()
                    if local_hash == remote_hash:
                        print(f"  SKIP  {langfuse_name}  (no changes)")
                        skipped += 1
                        continue

            # Build frontmatter
            fm_dict: dict[str, Any] = {
                "name": name,
                "version": version,
                "model": config.get("model", "claude-opus-4-7"),
                "temperature": config.get("temperature", 0.0),
                "max_tokens": config.get("max_tokens", 1024),
                "owner": "lex-agents",
            }
            fm_str = yaml.dump(fm_dict, default_flow_style=False, allow_unicode=True)
            content = f"---\n{fm_str}---\n\n{remote_body}\n"

            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            print(f"  PULL  {langfuse_name}  → {target_path.relative_to(REPO_ROOT)}")
            pulled += 1

        meta = data.get("meta", {})
        total_pages = meta.get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1

    return pulled, skipped, errors


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--direction",
        choices=["push", "pull", "both"],
        default="push",
        help="Sync direction (default: push)",
    )
    args = parser.parse_args()

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        print("WARNING: LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set — skipping sync.")
        sys.exit(0)

    try:
        client = LangfuseClient(public_key=public_key, secret_key=secret_key, host=host)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: Could not initialise Langfuse client: {exc} — skipping sync.")
        sys.exit(0)

    total_pushed = total_pulled = total_skipped = total_errors = 0

    if args.direction in ("push", "both"):
        print(f"\nPushing docs/prompts/ → Langfuse ({host})")
        prompts = collect_local_prompts()
        print(f"  Found {len(prompts)} local prompt file(s).")
        pushed, skipped, errors = push(client, prompts)
        total_pushed += pushed
        total_skipped += skipped
        total_errors += errors

    if args.direction in ("pull", "both"):
        print(f"\nPulling Langfuse ({host}) → docs/prompts/")
        pulled, skipped, errors = pull(client)
        total_pulled += pulled
        total_skipped += skipped
        total_errors += errors

    print("\n─── Summary ─────────────────────────────────────────────────────")
    if args.direction in ("push", "both"):
        print(f"  Pushed:  {total_pushed}")
    if args.direction in ("pull", "both"):
        print(f"  Pulled:  {total_pulled}")
    print(f"  Skipped: {total_skipped}")
    print(f"  Errors:  {total_errors}")

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
