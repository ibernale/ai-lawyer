"""Domain types for the Document Agents pipeline (ADR 0026)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field


SegmentType = Literal[
    "clausula",
    "considerando",
    "antecedente",
    "acuerdo",
    "resolucion",
    "fundamento",
    "firma",
    "anexo",
    "parrafo",
    "thread",
]


class DocumentSegment(BaseModel):
    """A logical unit of a parsed document, referenceable via [DOC:s]."""

    segment_id: str = Field(description="{doc_id}::{index}")
    index: int = Field(ge=1, description="1-based index — maps to [DOC:s]")
    segment_type: SegmentType = "parrafo"
    text: str
    page_start: int | None = None
    heading: str | None = None


class ParsedDocument(BaseModel):
    """In-memory representation of a parsed uploaded document.

    Never persisted to disk — only trace_id, sha256, and analysis summary
    are stored (privacy invariant, ADR 0026).
    """

    doc_id: str = Field(description="UUID assigned at upload")
    filename: str
    mime_type: str
    sha256: str = Field(description="hex SHA-256 of raw bytes")
    page_count: int | None = None
    text: str = Field(description="Full concatenated text — in-memory only")
    segments: list[DocumentSegment] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class ExtractedEntities(BaseModel):
    """Structured entities extracted from a ParsedDocument."""

    parties: list[str] = Field(default_factory=list)
    norms_referenced: list[str] = Field(default_factory=list)
    key_dates: list[date] = Field(default_factory=list)
    risk_clauses: list[str] = Field(default_factory=list)


class DocumentAnalysisResult(BaseModel):
    """Output of the Document Agents pipeline for a single document."""

    doc_id: str
    trace_id: str
    sha256: str
    filename: str
    segment_count: int
    entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    analysis_text: str = Field(
        description="Markdown answer with [DOC:s] and [REF:n] citations"
    )
    verification_status: Literal["green", "amber", "red"] = "amber"
    analysed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DocumentCompareResult(BaseModel):
    """Output of a document-comparison analysis (two documents)."""

    doc_ids: list[str] = Field(min_length=2, max_length=2)
    trace_id: str
    diff_text: str = Field(description="Markdown diff analysis with [DOC:s] citations")
    verification_status: Literal["green", "amber", "red"] = "amber"
    analysed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
