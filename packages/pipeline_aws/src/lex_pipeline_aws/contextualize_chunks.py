"""Lambda handler — ContextualizeChunks stage (ADR 0047).

Implements Anthropic's Contextual Retrieval technique: for each chunk, calls
Claude to generate a short context sentence that situates the chunk within the
full document. The context is prepended to the chunk text before embedding.

Reference: https://www.anthropic.com/news/contextual-retrieval

Input  (PipelineEvent fields used):
  doc_id          : set by FetchRaw
  source          : "boe" | "eur_lex"
  canonical_s3_key: set by ParseCanonical (for full document context)
  chunks_s3_key   : set by ChunkDocument

Output (new fields added to PipelineEvent):
  contextualized_s3_key : "s3://<canonical-bucket>/<doc_id>.contextualized.jsonl"
  status                : "success" | "error"

Environment variables:
  CANONICAL_BUCKET_NAME : S3 bucket (read chunks, write contextualized)
  ANTHROPIC_API_KEY     : Anthropic API key (or via Secrets Manager)
  ANTHROPIC_MODEL       : Claude model for contextualization
                          (default: claude-3-5-haiku-20241022 — cheap + fast)
  CONTEXT_BATCH_SIZE    : chunks per Claude prompt (default: 5)
  IDEMPOTENCY_TABLE     : DynamoDB table name
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

import boto3
import structlog

from lex_pipeline_aws.idempotency import (
    AlreadySucceeded,
    StillRunning,
    acquire_lock,
    fail_lock,
    release_lock,
)
from lex_pipeline_aws.types import PipelineEvent

logger: structlog.BoundLogger = structlog.get_logger(__name__)

CANONICAL_BUCKET = os.environ.get("CANONICAL_BUCKET_NAME", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
CONTEXT_BATCH_SIZE = int(os.environ.get("CONTEXT_BATCH_SIZE", "5"))

_CONTEXT_PROMPT = """\
<document>
{document_text}
</document>

Here is the chunk we want to situate within the above document:
<chunk>
{chunk_text}
</chunk>

Please give a short succinct context (2-3 sentences max) to situate this chunk
within the overall document for the purposes of improving search retrieval.
Answer only with the context, no preamble. Write in the same language as the document.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_s3_jsonl(s3_uri: str) -> list[dict[str, Any]]:
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=bucket, Key=key)
    lines = resp["Body"].read().decode("utf-8").strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]


def _read_s3_json(s3_uri: str) -> dict[str, Any]:
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(resp["Body"].read())


def _get_anthropic_key() -> str:
    """Get Anthropic API key from env or Secrets Manager."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    # Fallback: read from Secrets Manager
    secret_arn = os.environ.get("ANTHROPIC_SECRET_ARN", "")
    if secret_arn:
        sm = boto3.client("secretsmanager")
        resp = sm.get_secret_value(SecretId=secret_arn)
        secret = json.loads(resp["SecretString"])
        return secret.get("value", secret.get("api_key", ""))
    raise RuntimeError("ANTHROPIC_API_KEY or ANTHROPIC_SECRET_ARN must be set")


def _contextualize_chunks(
    document_text: str,
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add contextual prefix to each chunk using Claude.

    Uses prompt caching: the large document text is in the system prompt
    with `cache_control` to minimise token cost across chunk batches.
    """
    import anthropic

    api_key = _get_anthropic_key()
    client = anthropic.Anthropic(api_key=api_key)
    contextualized: list[dict[str, Any]] = []

    # Process in batches to reduce latency (each batch = 1 API call with caching)
    for i in range(0, len(chunks), CONTEXT_BATCH_SIZE):
        batch = chunks[i : i + CONTEXT_BATCH_SIZE]
        for chunk in batch:
            chunk_text = chunk.get("text", "")
            if not chunk_text.strip():
                contextualized.append(chunk)
                continue

            try:
                response = client.messages.create(
                    model=ANTHROPIC_MODEL,
                    max_tokens=256,
                    system=[
                        {
                            "type": "text",
                            "text": (
                                "You are an expert legal document analyst specialising in "
                                "Spanish and EU banking regulation. Your task is to provide "
                                "brief contextual summaries that help situate document chunks "
                                "for retrieval."
                            ),
                            # Cache the large document text across chunks in this batch
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[
                        {
                            "role": "user",
                            "content": _CONTEXT_PROMPT.format(
                                document_text=document_text[:4000],  # truncate for prompt
                                chunk_text=chunk_text,
                            ),
                        }
                    ],
                )
                context_sentence = response.content[0].text.strip()
                enriched = {**chunk, "context": context_sentence, "text": f"{context_sentence}\n{chunk_text}"}
            except Exception as exc:
                logger.warning("contextualize_chunk_error", chunk_id=chunk.get("chunk_id"), error=str(exc))
                # Don't fail the whole batch for a single chunk error; keep original text
                enriched = {**chunk, "context": "", "contextualize_error": str(exc)}

            contextualized.append(enriched)

    return contextualized


def _doc_to_text(canonical: dict[str, Any]) -> str:
    """Extract plain text from canonical doc for use as document context."""
    parts = [canonical.get("doc_title", "")]
    for item in canonical.get("items", [])[:50]:  # first 50 items for context
        title = item.get("title", "")
        if title:
            parts.append(title)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Step Functions Lambda handler for the ContextualizeChunks stage."""
    evt = PipelineEvent.from_dict(event)
    logger.info("contextualize_chunks_start", doc_id=evt.doc_id, chunks_count=evt.chunks_count)

    try:
        try:
            acquire_lock(evt.doc_id, "contextualize_chunks")
        except AlreadySucceeded as exc:
            logger.info("contextualize_chunks_cached", doc_id=evt.doc_id)
            return PipelineEvent.from_dict({**event, **exc.cached_output, "status": "success"}).to_dict()
        except StillRunning:
            raise

        # Read inputs
        chunks = _read_s3_jsonl(evt.chunks_s3_key)
        canonical = _read_s3_json(evt.canonical_s3_key)
        document_text = _doc_to_text(canonical)

        # Contextualize
        logger.info("contextualize_chunks_calling_claude", doc_id=evt.doc_id, chunks=len(chunks))
        contextualized = _contextualize_chunks(document_text, chunks)

        # Write output JSONL
        year = evt.run_date[:4]
        s3_key = f"{evt.source}/{year}/{evt.doc_id.replace('/', '_')}.contextualized.jsonl"
        jsonl_bytes = "\n".join(json.dumps(c, ensure_ascii=False) for c in contextualized).encode("utf-8")

        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=CANONICAL_BUCKET,
            Key=s3_key,
            Body=jsonl_bytes,
            ContentType="application/x-ndjson",
            Metadata={"doc_id": evt.doc_id, "chunks_count": str(len(contextualized))},
        )

        output_fields = {
            "contextualized_s3_key": f"s3://{CANONICAL_BUCKET}/{s3_key}",
            "status": "success",
        }
        release_lock(evt.doc_id, "contextualize_chunks", output_fields)
        return PipelineEvent.from_dict({**event, **output_fields}).to_dict()

    except (AlreadySucceeded, StillRunning):
        raise
    except Exception as exc:
        logger.error("contextualize_chunks_error", error=str(exc), doc_id=evt.doc_id)
        fail_lock(evt.doc_id, "contextualize_chunks", str(exc))
        raise
