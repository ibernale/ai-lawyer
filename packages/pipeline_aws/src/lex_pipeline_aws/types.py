"""Shared event envelope for Step Functions pipeline stages (ADR 0047).

Every Lambda handler in the pipeline receives and returns a ``PipelineEvent``.
Step Functions passes the entire output of one state as the input to the next,
so the envelope accumulates fields as it moves through the pipeline.

Field contract:
  - Fields added by a stage are guaranteed to exist for all downstream stages.
  - Fields are never removed (downstream stages may ignore them).
  - ``status`` is the canonical field checked by the catch/retry logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class PipelineEvent:
    # ── Trigger fields (set by EventBridge / manual invocation) ───────────
    source: str          # "boe" | "eur_lex"
    run_date: str        # ISO date: "2026-05-14"
    doc_id: str = ""     # Unique document identifier (set by FetchRaw)

    # ── FetchRaw output ────────────────────────────────────────────────────
    raw_s3_key: str = ""         # s3://raw-bucket/<key>
    raw_content_type: str = ""   # "application/xml" | "application/json"
    raw_byte_size: int = 0

    # ── ParseCanonical output ──────────────────────────────────────────────
    canonical_s3_key: str = ""   # s3://canonical-bucket/<key>
    doc_title: str = ""
    doc_date: str = ""           # ISO date
    doc_type: str = ""           # "reglamento" | "directiva" | "circular" | etc.
    sections_count: int = 0

    # ── ChunkDocument output ───────────────────────────────────────────────
    chunks_s3_key: str = ""      # s3://canonical-bucket/<key>.chunks.jsonl
    chunks_count: int = 0

    # ── ContextualizeChunks output ────────────────────────────────────────
    contextualized_s3_key: str = ""  # s3://canonical-bucket/<key>.contextualized.jsonl

    # ── EmbedChunks / IndexToQdrant output (ECS RunTask — set by task) ───
    embedding_model: str = ""
    vectors_indexed: int = 0
    qdrant_collection: str = ""

    # ── Pipeline metadata ─────────────────────────────────────────────────
    status: str = "pending"           # pending | running | success | error
    error_message: str = ""
    pipeline_version: str = "0.1.0"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PipelineEvent":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        extra = {k: v for k, v in d.items() if k not in known}
        filtered = {k: v for k, v in d.items() if k in known}
        evt = cls(**filtered)
        evt.extra.update(extra)
        return evt
