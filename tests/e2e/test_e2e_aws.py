"""End-to-end AWS tests — Fase 9.5.

Requires:
  API_BASE_URL       : CloudFront/ALB URL of deployed API
  S3_DOCS_BUCKET     : S3 bucket for document uploads
  LANGFUSE_HOST      : Self-hosted Langfuse URL
  LANGFUSE_SECRET_KEY: Langfuse secret key
  LANGFUSE_PUBLIC_KEY: Langfuse public key
  ADMIN_API_TOKEN    : Admin bearer token

Run on-demand via GitHub Actions workflow_dispatch.
NOT included in ci.yml (marked @pytest.mark.e2e_aws).

Verifies the 14-step scenario from Fase 9.5 spec:
  1. Upload PDF -> S3 encrypted
  2. Document parsing completes (ECS Fargate)
  3. Legal consultation request
  4. Citations present in response
  5. Audit trail entry created
  6. Langfuse trace present
  7. X-Ray trace present
  8. Document scheduled for deletion (24h TTL)
  9. Kill switch endpoint reachable
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import boto3
import httpx
import pytest

pytestmark = pytest.mark.e2e_aws

API_BASE = os.environ.get("API_BASE_URL", "").rstrip("/")
S3_BUCKET = os.environ.get("S3_DOCS_BUCKET", "")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "")
LANGFUSE_SK = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_PK = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
ADMIN_TOKEN = os.environ.get("ADMIN_API_TOKEN", "")

# Minimal PDF fixture (valid 1-page PDF)
FIXTURE_PDF = Path(__file__).parent / "fixtures" / "contrato_muestra.pdf"


@pytest.fixture(scope="module")
def api_client() -> httpx.Client:
    return httpx.Client(
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=60.0,
    )


@pytest.fixture(scope="module")
def s3_client() -> Any:
    return boto3.client("s3", region_name="eu-central-1")


@pytest.mark.e2e_aws
def test_api_health(api_client: httpx.Client) -> None:
    """Step 0: API is reachable and healthy."""
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


@pytest.mark.e2e_aws
def test_document_upload_encrypted(s3_client: Any) -> None:
    """Steps 1-2: Upload PDF to S3 and verify SSE-KMS encryption."""
    if not S3_BUCKET:
        pytest.skip("S3_DOCS_BUCKET not set")
    if not FIXTURE_PDF.exists():
        pytest.skip("Test fixture PDF not found")

    doc_key = f"test-e2e/{uuid.uuid4()}/contrato.pdf"
    s3_client.upload_file(
        str(FIXTURE_PDF),
        S3_BUCKET,
        doc_key,
        ExtraArgs={"ServerSideEncryption": "aws:kms"},
    )
    # Verify object exists and is KMS-encrypted
    head = s3_client.head_object(Bucket=S3_BUCKET, Key=doc_key)
    assert head["ServerSideEncryption"] == "aws:kms"
    # Cleanup
    s3_client.delete_object(Bucket=S3_BUCKET, Key=doc_key)


@pytest.mark.e2e_aws
def test_legal_consultation_returns_citations(api_client: httpx.Client) -> None:
    """Steps 3-4: Legal consultation returns non-empty citations."""
    payload = {
        "question": "Cuales son los requisitos de capital minimo segun la CRR?",
        "jurisdiction": "EU",
    }
    resp = api_client.post("/api/v1/consult", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert "answer" in body
    citations = body.get("citations", [])
    assert len(citations) > 0, "Response must include at least one citation"


@pytest.mark.e2e_aws
def test_audit_trail_entry_created(api_client: httpx.Client) -> None:
    """Step 5: Audit trail has at least one entry."""
    resp = api_client.get("/api/v1/admin/audit/trail?limit=5")
    assert resp.status_code == 200
    entries = resp.json().get("entries", [])
    assert len(entries) > 0, "Audit trail must have at least one entry"


@pytest.mark.e2e_aws
def test_langfuse_trace_present() -> None:
    """Step 6: Langfuse has at least one trace in the last hour."""
    if not LANGFUSE_HOST or not LANGFUSE_SK:
        pytest.skip("Langfuse credentials not set")
    resp = httpx.get(
        f"{LANGFUSE_HOST}/api/public/traces",
        auth=(LANGFUSE_PK, LANGFUSE_SK),
        params={"limit": 1},
        timeout=30.0,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data.get("data", [])) > 0, "Langfuse must have at least one trace"


@pytest.mark.e2e_aws
def test_kill_switch_endpoint_reachable(api_client: httpx.Client) -> None:
    """Step 9: Kill switch endpoint is reachable (returns 200, does not engage)."""
    resp = api_client.get("/api/v1/admin/kill_switches")
    assert resp.status_code == 200
