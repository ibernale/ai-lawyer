"""Canonical document model and Chunk type for the ingestion pipeline."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal

from lex_agents_shared.types import ChunkMetadata
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Source and jurisdiction literals (shared by all canonical models)
# ---------------------------------------------------------------------------

NormativeSource = Literal[
    "boe", "eurlex", "aepd", "edpb", "bde", "eba", "esma", "legislation_uk", "fca",
]
JurisprudenciaSource = Literal["cendoj", "tribunal_constitucional"]
BulletinSource = Literal["inlabs_dou", "sidof_dof"]
CommercialSource = Literal["aranzadi", "laley", "tirant"]

AnySource = Literal[
    "boe", "eurlex", "aepd", "edpb", "bde", "eba", "esma", "legislation_uk", "fca",
    "cendoj", "tribunal_constitucional",
    "inlabs_dou", "sidof_dof",
    "aranzadi", "laley", "tirant",
]

AnyJurisdiction = Literal["ES", "EU", "GB", "BR", "MX"]

# ---------------------------------------------------------------------------
# Raw fetch result
# ---------------------------------------------------------------------------

class RawDocument(BaseModel):
    source: str
    source_id: str
    raw_url: str
    content_type: Literal["xml", "html", "pdf"]
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
    ]
    number: str
    title: str = ""


# ---------------------------------------------------------------------------
# Canonical document
# ---------------------------------------------------------------------------

class CanonicalDocument(BaseModel):
    id: str = ""
    jurisdiction: AnyJurisdiction = "EU"
    source: AnySource
    source_id: str
    type: Literal[
        "regulation", "directive", "ley", "real_decreto", "circular",
        "resolution", "guideline", "opinion", "qa", "other",
    ] = "other"
    title: str = ""
    publication_date: date = Field(default_factory=date.today)
    entry_into_force: date | None = None
    status: Literal[
        "vigente", "derogado", "consulta_publica", "transposicion", "unknown"
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
# Case-law canonical model (CENDOJ, Tribunal Constitucional)
# ---------------------------------------------------------------------------

class CanonicalCaseLaw(CanonicalDocument):
    """Canonical representation of a court decision.

    Extends CanonicalDocument with structured judicial metadata required by
    the strict verifier (ADR 0024). All CENDOJ/TC documents parse into this type.
    """

    source: JurisprudenciaSource  # type: ignore[assignment]
    jurisdiction: Literal["ES"] = "ES"  # type: ignore[assignment]
    type: Literal["sentencia", "auto", "providencia"] = "sentencia"  # type: ignore[assignment]

    ecli: str | None = None
    court: str = ""
    chamber: str | None = None
    judges: list[str] = Field(default_factory=list)
    case_number: str = ""
    decision_date: date = Field(default_factory=date.today)
    operative_part: str = ""
    grounds: list[str] = Field(default_factory=list)
    related_norms: list[str] = Field(default_factory=list)
    anonymized: bool = True


# ---------------------------------------------------------------------------
# Bulletin canonical model (DOU Brasil, DOF México)
# ---------------------------------------------------------------------------

class CanonicalBulletin(CanonicalDocument):
    """Canonical representation of an official gazette entry.

    Used for INLABS DOU (Brazil) and SIDOF DOF (Mexico).
    """

    source: BulletinSource  # type: ignore[assignment]
    jurisdiction: Literal["BR", "MX"]  # type: ignore[assignment]
    type: Literal[  # type: ignore[assignment]
        "decreto", "lei", "resolucao", "resolución", "circular",
        "nom", "nmx", "acuerdo", "other",
    ] = "other"

    bulletin: str = ""
    section: str | None = None
    issue_number: str | None = None
    document_type: str = ""
    issuing_authority: str = ""
    summary: str | None = None


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
