"""Document upload and analysis endpoints — /api/v1/documents.

Per-tenant document collections in Qdrant: ``docs_{tenant_id}``.
Supports PDF, DOCX, and plain-text uploads up to ``docs_max_bytes``.
Analysis and comparison use claude-sonnet-4-6 with the full document as context.

Text extraction uses DoclingExtractor (Fase 11C.3):
- Docling>=2.0.0 when installed: layout-aware Markdown output, table extraction.
- Fallback to pdfminer (PDF) / python-docx (DOCX) when Docling is not available.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from lex_agents_ingest.docling_extractor import get_extractor
from lex_agents_ingest.embedder import BgeM3Embedder, EmbeddingResult
from lex_agents_shared.anthropic_client import MODEL_SONNET, AnthropicClientWrapper
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from lex_agents_api.auth import CurrentUser, require_auth
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

_DENSE_VECTOR = "dense"
_DENSE_DIM = 1024
_DOC_TTL_DAYS = 7  # uploaded docs expire after 7 days
_MAX_CHUNK_CHARS = 1200


# ---------------------------------------------------------------------------
# Collection naming
# ---------------------------------------------------------------------------


def docs_collection_name(tenant_id: str, prefix: str = "docs") -> str:
    """Return the per-tenant document collection name.

    Examples::

        docs_collection_name("default")        → "docs_default"
        docs_collection_name("santander_es")   → "docs_santander_es"
    """
    safe = re.sub(r"[^a-z0-9]", "_", tenant_id.lower())[:50]
    return f"{prefix}_{safe}"


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    sha256: str
    mime_type: str
    segment_count: int
    page_count: int | None
    expires_at: str


class AnalyzeRequest(BaseModel):
    query: str = Field(default="Analiza este documento.", max_length=2000)
    mode: str = Field(default="riesgos")


class AnalysisResponse(BaseModel):
    doc_id: str
    trace_id: str
    filename: str
    mode: str
    analysis_text: str
    segment_count: int
    verification_status: str
    analysed_at: str


class CompareRequest(BaseModel):
    doc_ids: list[str] = Field(min_length=2, max_length=2)
    query: str = Field(default="Compara estos dos documentos.", max_length=2000)


class CompareResponse(BaseModel):
    doc_ids: list[str]
    trace_id: str
    diff_text: str
    verification_status: str
    analysed_at: str


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_embedder(model: str) -> BgeM3Embedder:
    return BgeM3Embedder(model=model)


@lru_cache(maxsize=1)
def _get_qdrant(url: str, api_key: str) -> QdrantClient:
    return QdrantClient(url=url, api_key=api_key or None)


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------


def _ensure_docs_collection(client: QdrantClient, collection_name: str) -> None:
    """Create a dense-only collection for user documents if it does not exist.

    User-uploaded docs use dense-only vectors (no sparse) because:
    - Voyage AI does not produce sparse vectors.
    - The shared regulatory corpus uses hybrid (dense+sparse); docs don't need it.
    """
    existing = {c.name for c in client.get_collections().collections}
    if collection_name in existing:
        return
    client.create_collection(
        collection_name=collection_name,
        vectors_config={
            _DENSE_VECTOR: VectorParams(size=_DENSE_DIM, distance=Distance.COSINE),
        },
    )
    logger.info("docs_collection_created", collection=collection_name)


def _make_chunk_point_id(doc_id: str, chunk_idx: int) -> int:
    """Derive a stable uint64 from doc_id + chunk index."""
    raw = hashlib.sha256(f"{doc_id}:{chunk_idx}".encode()).hexdigest()
    return int(raw[:16], 16)


# ---------------------------------------------------------------------------
# Text extraction — delegates to DoclingExtractor (Fase 11C.3)
# ---------------------------------------------------------------------------


def _extract_text(
    data: bytes, mime_type: str, filename: str
) -> tuple[str, int | None]:
    """Extract text via DoclingExtractor.

    Uses Docling (layout-aware, table extraction, Markdown output) when
    installed; falls back to pdfminer/python-docx otherwise.
    """
    try:
        return get_extractor().extract(data, mime_type, filename)
    except Exception as exc:
        logger.warning("text_extraction_failed", filename=filename, exc=str(exc))
        raise HTTPException(
            status_code=422,
            detail=f"No se pudo extraer texto del documento: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _chunk_text(
    text: str,
    doc_id: str,
    filename: str,
    expires_at: str,
) -> list[dict[str, Any]]:
    """Split text into paragraph-based chunks of ≤ _MAX_CHUNK_CHARS."""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else ["(sin contenido)"]

    raw_chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 2 > _MAX_CHUNK_CHARS:
            raw_chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}".strip() if current else para
    if current:
        raw_chunks.append(current)

    return [
        {
            "doc_id": doc_id,
            "filename": filename,
            "chunk_idx": i,
            "text": chunk,
            "expires_at": expires_at,
        }
        for i, chunk in enumerate(raw_chunks)
    ]


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

_MODE_PROMPTS: dict[str, str] = {
    "resumen_ejecutivo": (
        "Redacta un resumen ejecutivo conciso del siguiente documento legal, "
        "destacando los puntos principales, obligaciones y compromisos clave."
    ),
    "analisis_clausulas": (
        "Analiza las cláusulas principales del documento. Para cada una, indica "
        "su alcance, las obligaciones que genera y sus posibles implicaciones jurídicas."
    ),
    "riesgos": (
        "Identifica y evalúa los riesgos jurídicos del documento. "
        "Clasifícalos por gravedad (alto / medio / bajo) y sugiere medidas de mitigación."
    ),
    "comparativa": (
        "Compara el contenido del documento con la normativa vigente (bancaria, "
        "RGPD, mercantil) y destaca divergencias o cumplimientos notables."
    ),
}

_SYSTEM_PROMPT = (
    "Eres un abogado especializado en derecho bancario y regulatorio español y europeo. "
    "Analiza documentos legales con rigor, precisión y fundamento normativo. "
    "Cuando realices afirmaciones normativas, indícalas explícitamente. "
    "Redacta siempre en español."
)


async def _call_llm(
    client: AnthropicClientWrapper,
    system: str,
    user: str,
) -> str:
    """Run the synchronous messages_create in a thread pool."""
    resp = await asyncio.to_thread(
        client.messages_create,
        model=MODEL_SONNET,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text if resp.content else ""  # type: ignore[union-attr]


async def _fetch_doc_chunks(
    qdrant: QdrantClient,
    collection_name: str,
    doc_id: str,
) -> list[Any]:
    """Scroll all chunks for *doc_id* from Qdrant. Raises 404 if none found."""
    doc_filter = Filter(
        must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
    )
    try:
        results, _ = await asyncio.to_thread(
            qdrant.scroll,
            collection_name=collection_name,
            scroll_filter=doc_filter,
            limit=512,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as exc:
        logger.warning("qdrant_scroll_failed", doc_id=doc_id, exc=str(exc))
        raise HTTPException(
            status_code=404, detail=f"Documento {doc_id!r} no encontrado"
        ) from exc
    if not results:
        raise HTTPException(
            status_code=404, detail=f"Documento {doc_id!r} no encontrado"
        )
    return sorted(
        results,
        key=lambda r: r.payload.get("chunk_idx", 0) if r.payload else 0,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile,
    current_user: CurrentUser = Depends(require_auth),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    """Upload a PDF, DOCX, or TXT document, chunk it, embed it, and store it
    in the per-tenant Qdrant collection ``docs_{tenant_id}``."""
    data = await file.read()
    if len(data) > settings.docs_max_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Archivo demasiado grande "
                f"(límite: {settings.docs_max_bytes // 1024} KB)"
            ),
        )

    sha256 = hashlib.sha256(data).hexdigest()
    doc_id = str(uuid.uuid4())
    filename = file.filename or "documento"
    mime_type = file.content_type or "application/octet-stream"
    expires_at = (datetime.now(UTC) + timedelta(days=_DOC_TTL_DAYS)).isoformat()

    # Extract text --------------------------------------------------------
    text, page_count = _extract_text(data, mime_type, filename)

    # Chunk ---------------------------------------------------------------
    chunks = _chunk_text(text, doc_id, filename, expires_at)
    if not chunks:
        raise HTTPException(
            status_code=422,
            detail="El documento no tiene contenido textual extraíble",
        )

    # Embed ---------------------------------------------------------------
    embedder = _get_embedder(settings.embedder_model)
    texts = [c["text"] for c in chunks]
    embeddings: list[EmbeddingResult] = await asyncio.to_thread(
        embedder.embed_batch, texts, "document"
    )

    # Upsert to Qdrant ---------------------------------------------------
    qdrant = _get_qdrant(
        settings.qdrant_url, settings.qdrant_api_key.get_secret_value()
    )
    collection_name = docs_collection_name(
        current_user.tenant_id, settings.qdrant_docs_prefix
    )
    await asyncio.to_thread(_ensure_docs_collection, qdrant, collection_name)

    points = [
        PointStruct(
            id=_make_chunk_point_id(doc_id, i),
            vector={_DENSE_VECTOR: emb.dense},
            payload=chunk,
        )
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
    ]
    await asyncio.to_thread(qdrant.upsert, collection_name=collection_name, points=points)

    logger.info(
        "document_uploaded",
        doc_id=doc_id,
        filename=filename,
        segment_count=len(chunks),
        tenant_id=current_user.tenant_id,
    )

    return UploadResponse(
        doc_id=doc_id,
        filename=filename,
        sha256=sha256,
        mime_type=mime_type,
        segment_count=len(chunks),
        page_count=page_count,
        expires_at=expires_at,
    )


@router.post("/{doc_id}/analyze", response_model=AnalysisResponse)
async def analyze_document(
    doc_id: str,
    body: AnalyzeRequest,
    current_user: CurrentUser = Depends(require_auth),
    settings: Settings = Depends(get_settings),
) -> AnalysisResponse:
    """Analyze a previously uploaded document via LLM.

    Retrieves all chunks from the tenant collection, assembles them as context,
    and calls the LLM with the selected analysis *mode*.
    """
    qdrant = _get_qdrant(
        settings.qdrant_url, settings.qdrant_api_key.get_secret_value()
    )
    collection_name = docs_collection_name(
        current_user.tenant_id, settings.qdrant_docs_prefix
    )

    chunks = await _fetch_doc_chunks(qdrant, collection_name, doc_id)
    filename = (
        chunks[0].payload.get("filename", "documento") if chunks[0].payload else "documento"
    )
    context_parts = [
        f"[Fragmento {r.payload.get('chunk_idx', i)}]\n{r.payload.get('text', '')}"
        for i, r in enumerate(chunks)
        if r.payload
    ]
    context = "\n\n---\n\n".join(context_parts)

    mode_prompt = _MODE_PROMPTS.get(body.mode, _MODE_PROMPTS["riesgos"])
    user_message = (
        f"{mode_prompt}\n\n"
        f"**Consulta adicional:** {body.query}\n\n"
        f"**Documento:** {filename}\n\n"
        f"{context}"
    )

    client = AnthropicClientWrapper(
        api_key=settings.anthropic_api_key.get_secret_value()
    )
    try:
        analysis_text = await _call_llm(client, _SYSTEM_PROMPT, user_message)
    except Exception as exc:
        logger.error("analyze_llm_failed", doc_id=doc_id, exc=str(exc))
        raise HTTPException(
            status_code=502,
            detail="Error al analizar el documento con el modelo de IA",
        ) from exc

    return AnalysisResponse(
        doc_id=doc_id,
        trace_id=str(uuid.uuid4()),
        filename=filename,
        mode=body.mode,
        analysis_text=analysis_text,
        segment_count=len(chunks),
        verification_status="amber",  # no citation verification for uploaded docs
        analysed_at=datetime.now(UTC).isoformat(),
    )


@router.post("/compare", response_model=CompareResponse)
async def compare_documents(
    body: CompareRequest,
    current_user: CurrentUser = Depends(require_auth),
    settings: Settings = Depends(get_settings),
) -> CompareResponse:
    """Compare two previously uploaded documents side-by-side via LLM."""
    qdrant = _get_qdrant(
        settings.qdrant_url, settings.qdrant_api_key.get_secret_value()
    )
    collection_name = docs_collection_name(
        current_user.tenant_id, settings.qdrant_docs_prefix
    )

    # Fetch both docs in parallel
    chunks_a, chunks_b = await asyncio.gather(
        _fetch_doc_chunks(qdrant, collection_name, body.doc_ids[0]),
        _fetch_doc_chunks(qdrant, collection_name, body.doc_ids[1]),
    )

    def _assemble(chunks: list[Any]) -> tuple[str, str]:
        fn = (
            chunks[0].payload.get("filename", "documento")
            if chunks[0].payload
            else "documento"
        )
        text = "\n\n".join(
            r.payload.get("text", "") for r in chunks if r.payload
        )
        return fn, text

    filename_a, text_a = _assemble(chunks_a)
    filename_b, text_b = _assemble(chunks_b)

    system_prompt = (
        "Eres un abogado especializado en derecho bancario y regulatorio español y europeo. "
        "Compara documentos legales identificando diferencias sustanciales, cláusulas divergentes "
        "y riesgos diferenciales. Estructura tu respuesta con secciones claras. "
        "Redacta siempre en español."
    )
    user_message = (
        f"Compara los siguientes dos documentos legales.\n\n"
        f"**Instrucción adicional:** {body.query}\n\n"
        f"---\n**DOCUMENTO A: {filename_a}**\n\n{text_a}\n\n"
        f"---\n**DOCUMENTO B: {filename_b}**\n\n{text_b}\n"
    )

    client = AnthropicClientWrapper(
        api_key=settings.anthropic_api_key.get_secret_value()
    )
    try:
        diff_text = await _call_llm(client, system_prompt, user_message)
    except Exception as exc:
        logger.error("compare_llm_failed", doc_ids=body.doc_ids, exc=str(exc))
        raise HTTPException(
            status_code=502,
            detail="Error al comparar los documentos con el modelo de IA",
        ) from exc

    return CompareResponse(
        doc_ids=body.doc_ids,
        trace_id=str(uuid.uuid4()),
        diff_text=diff_text,
        verification_status="amber",
        analysed_at=datetime.now(UTC).isoformat(),
    )


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: str,
    current_user: CurrentUser = Depends(require_auth),
    settings: Settings = Depends(get_settings),
) -> None:
    """Delete all chunks for *doc_id* from the tenant's document collection.

    Idempotent — returns 204 even if the document did not exist.
    """
    qdrant = _get_qdrant(
        settings.qdrant_url, settings.qdrant_api_key.get_secret_value()
    )
    collection_name = docs_collection_name(
        current_user.tenant_id, settings.qdrant_docs_prefix
    )
    delete_filter = Filter(
        must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
    )
    try:
        await asyncio.to_thread(
            qdrant.delete,
            collection_name=collection_name,
            points_selector=FilterSelector(filter=delete_filter),
        )
        logger.info(
            "document_deleted",
            doc_id=doc_id,
            tenant_id=current_user.tenant_id,
        )
    except Exception as exc:
        # Swallow errors — collection may not exist yet; delete is idempotent
        logger.debug("document_delete_skipped", doc_id=doc_id, exc=str(exc))
