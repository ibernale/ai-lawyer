"""Canonical document model and Chunk type for the ingestion pipeline."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal

from lex_agents_shared.types import ChunkMetadata
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Raw fetch result
# ---------------------------------------------------------------------------

class RawDocument(BaseModel):
    source: str
    source_id: str
    raw_url: str
    content_type: Literal["xml", "html", "pdf", "json"]
    raw_bytes: bytes
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    checksum: str = ""

    def model_post_init(self, __context: object) -> None:
        if not self.checksum:
            object.__setattr__(
                self,
                "checksum",
                hashlib.sha256(self.raw_bytes).hexdigest(),
            )


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------

class HierarchyNode(BaseModel):
    level: Literal[
        "libro", "titulo", "capitulo", "seccion",
        "articulo", "apartado", "considerando", "anexo",
        "organismo",
    ]
    number: str = ""
    title: str = ""
    label: str = ""


# ---------------------------------------------------------------------------
# Canonical document
# ---------------------------------------------------------------------------

class CanonicalDocument(BaseModel):
    id: str = ""
    jurisdiction: Literal["ES", "EU", "GB", "US", "GLOBAL", "BR", "AR"] = "EU"
    source: Literal[
        "boe",
        "eurlex",
        "aepd",
        "edpb",
        "bde",
        "eba",
        "esma",
        "legislation_uk",
        "fca",
        # 11C.1 new sources
        "cnmc",
        "sepblac",
        "bcbs_bis",
        "federal_register",
        "bcb_brasil",
        "bcra",
    ]
    source_id: str
    type: Literal[
        "regulation", "directive", "ley", "real_decreto", "circular",
        "resolution", "guideline", "opinion", "qa", "other",
        # 11C.1 extended types
        "resolucion", "resolucao", "normativo", "comunicacion", "comunicado",
        "rule", "proposed_rule", "standard", "consultive_document", "working_paper",
        "report", "guia", "instruccion", "memoria", "documento",
        "nota_tecnica", "texto_ordenado",
    ] = "other"
    title: str = ""
    publication_date: date = Field(default_factory=date.today)
    entry_into_force: date | None = None
    status: Literal[
        "vigente", "derogado", "consulta_publica", "transposicion", "unknown",
        "final", "propuesta", "consultiva",
    ] = "unknown"
    hierarchy: list[HierarchyNode] = Field(default_factory=list)
    full_text: str = ""
    raw_url: str = ""
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    checksum: str = ""
    # Extended metadata — source-specific fields stored as free-form dict
    extra: dict[str, str] = Field(default_factory=dict)
    domain: str = ""

    def model_post_init(self, __context: object) -> None:
        if not self.id:
            object.__setattr__(
                self,
                "id",
                hashlib.sha256(
                    f"{self.source}::{self.source_id}".encode()
                ).hexdigest()[:16],
            )
        if not self.checksum and self.full_text:
            object.__setattr__(
                self,
                "checksum",
                hashlib.sha256(self.full_text.encode()).hexdigest(),
            )


# ---------------------------------------------------------------------------
# Chunk — extends ChunkMetadata with text fields
# ---------------------------------------------------------------------------

class Chunk(ChunkMetadata):
    """A retrieval-ready chunk: ChunkMetadata fields + text content."""

    text: str = Field(description="Raw chunk text (article / apartado / considerando)")
    context_text: str = Field(
        default="",
        description="Contextual summary prepended for retrieval (Contextual Retrieval)",
    )
