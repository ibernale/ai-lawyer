"""Load versioned prompt files from docs/prompts/<name>/v<N>.md."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class PromptConfig:
    name: str
    version: int
    model: str
    temperature: float
    max_tokens: int
    owner: str
    body: str
    content_hash: str


_CACHE: dict[tuple[str, int], PromptConfig] = {}


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


def load_prompt(name: str, version: int = 1) -> PromptConfig:
    """Load prompt config from docs/prompts/<name>/v<version>.md with in-memory cache."""
    key = (name, version)
    if key in _CACHE:
        return _CACHE[key]

    repo_root = _find_repo_root(Path(__file__).parent)
    prompt_path = repo_root / "docs" / "prompts" / name / f"v{version}.md"

    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")

    raw = prompt_path.read_text(encoding="utf-8")

    if not raw.startswith("---"):
        raise ValueError(f"Missing YAML frontmatter in {prompt_path}")

    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Malformed frontmatter in {prompt_path}")

    frontmatter = yaml.safe_load(parts[1])
    body = parts[2].strip()
    content_hash = hashlib.sha256(body.encode()).hexdigest()

    cfg = PromptConfig(
        name=str(frontmatter["name"]),
        version=int(frontmatter["version"]),
        model=str(frontmatter["model"]),
        temperature=float(frontmatter["temperature"]),
        max_tokens=int(frontmatter["max_tokens"]),
        owner=str(frontmatter.get("owner", "")),
        body=body,
        content_hash=content_hash,
    )
    _CACHE[key] = cfg
    return cfg
