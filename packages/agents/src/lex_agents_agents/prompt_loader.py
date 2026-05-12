"""Load versioned prompt files from docs/prompts/<name>/v<N>.md.

Also provides :class:`LangfusePromptLoader`, an optional wrapper that fetches
prompts from Langfuse Prompt Management with a TTL cache and automatic fallback
to the filesystem loader when Langfuse is unavailable or not configured.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Optional langfuse SDK — import only if installed
try:
    from langfuse import Langfuse as _LangfuseSDK  # type: ignore[import-untyped]

    _LANGFUSE_AVAILABLE = True
except ImportError:
    _LangfuseSDK = None  # type: ignore[assignment,misc]
    _LANGFUSE_AVAILABLE = False


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


class PromptLoader:
    """Filesystem-based prompt loader.

    Wraps the module-level :func:`load_prompt` function as a reusable object so
    it can be composed (e.g. passed to :class:`LangfusePromptLoader`).
    """

    def load(self, name: str, version: int = 1) -> PromptConfig:
        """Load prompt from the filesystem (with in-memory cache)."""
        return load_prompt(name, version)


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


class LangfusePromptLoader:
    """Optional Langfuse Prompt Management loader with filesystem fallback.

    Fetches prompts from Langfuse if the SDK is installed and
    ``LANGFUSE_PUBLIC_KEY`` is set in the environment.  Falls back to the
    wrapped :class:`PromptLoader` (filesystem) when:

    - The ``langfuse`` package is not installed.
    - ``LANGFUSE_PUBLIC_KEY`` is not set.
    - Any exception is raised during the Langfuse API call.

    Results are cached in-process with a configurable TTL (default 5 minutes)
    to avoid hammering the API on every request.
    """

    def __init__(self, base_loader: PromptLoader, ttl_seconds: int = 300) -> None:
        self._base = base_loader
        self._ttl = ttl_seconds
        # cache: prompt_name → (PromptConfig, monotonic timestamp)
        self._cache: dict[str, tuple[PromptConfig, float]] = {}
        self._enabled = _LANGFUSE_AVAILABLE and bool(os.getenv("LANGFUSE_PUBLIC_KEY"))

    def load(self, name: str) -> PromptConfig:
        """Load prompt from Langfuse if available, fallback to filesystem."""
        # Check TTL cache first
        if name in self._cache:
            config, cached_at = self._cache[name]
            if time.monotonic() - cached_at < self._ttl:
                return config

        if self._enabled:
            try:
                config = self._fetch_from_langfuse(name)
                self._cache[name] = (config, time.monotonic())
                return config
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "langfuse_prompt_fallback name=%s error=%s",
                    name,
                    str(exc),
                )

        return self._base.load(name)

    def _fetch_from_langfuse(self, name: str) -> PromptConfig:
        """Fetch prompt from Langfuse API. Raises on failure."""
        if not _LANGFUSE_AVAILABLE or _LangfuseSDK is None:
            raise RuntimeError("langfuse package is not installed")

        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

        client = _LangfuseSDK(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )

        prompt_obj = client.get_prompt(name, label="production")

        # The langfuse SDK returns a prompt object; extract text content
        # depending on whether it's a "text" or "chat" prompt type.
        raw_prompt = prompt_obj.prompt
        if isinstance(raw_prompt, str):
            body = raw_prompt
        elif isinstance(raw_prompt, list):
            # Chat prompt — join all message contents for body representation
            parts_text = []
            for msg in raw_prompt:
                if isinstance(msg, dict):
                    parts_text.append(str(msg.get("content", "")))
                else:
                    parts_text.append(str(msg))
            body = "\n\n".join(parts_text)
        else:
            body = str(raw_prompt)

        config_data: dict = getattr(prompt_obj, "config", {}) or {}
        content_hash = hashlib.sha256(body.encode()).hexdigest()

        return PromptConfig(
            name=name,
            version=getattr(prompt_obj, "version", 1),
            model=str(config_data.get("model", "claude-opus-4-7")),
            temperature=float(config_data.get("temperature", 0.0)),
            max_tokens=int(config_data.get("max_tokens", 1024)),
            owner=str(config_data.get("owner", "")),
            body=body,
            content_hash=content_hash,
        )
