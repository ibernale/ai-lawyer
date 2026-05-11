"""Raw download assets — one per source.

Each asset fetches documents from its source, writes them to
data/raw/<source>/ via IngestStorage, and returns metadata.
Assets are idempotent: documents whose checksum matches the stored
version are skipped.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import structlog
from dagster import (
    AssetCheckResult,
    AssetExecutionContext,
    DataVersion,
    Output,
    asset,
    asset_check,
)
from lex_agents_ingest.storage import IngestStorage

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DATA_DIR = Path(os.environ.get("LEX_DATA_DIR", "data"))
_HEADERS = {"User-Agent": "lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)"}


def _make_storage() -> IngestStorage:
    return IngestStorage(base_dir=_DATA_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_source_fetch(source_id: str, doc_ids: list[str] | None = None) -> dict[str, Any]:
    """Sync wrapper: build source, list docs, fetch, write raw. Returns report dict."""
    import httpx
    from lex_agents_ingest.sources.boe import BoeSource
    from lex_agents_ingest.sources.eurlex import EurlexSource

    source_map = {
        "boe": BoeSource,
        "eurlex": EurlexSource,
    }

    # Lazy import new sources (may not exist yet in dev)
    try:
        from lex_agents_ingest.sources.aepd import AepdSource
        source_map["aepd"] = AepdSource  # type: ignore[assignment]
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.edpb import EdpbSource
        source_map["edpb"] = EdpbSource  # type: ignore[assignment]
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.bde import BdeSource
        source_map["bde"] = BdeSource  # type: ignore[assignment]
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.eba import EbaSource
        source_map["eba"] = EbaSource  # type: ignore[assignment]
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.esma import EsmaSource
        source_map["esma"] = EsmaSource  # type: ignore[assignment]
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.legislation_uk import LegislationUkSource
        source_map["legislation_uk"] = LegislationUkSource  # type: ignore[assignment]
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.fca import FcaSource
        source_map["fca"] = FcaSource  # type: ignore[assignment]
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.cendoj import CendojSource
        source_map["cendoj"] = CendojSource  # type: ignore[assignment]
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.tc import TribunalConstitucionalSource
        source_map["tc"] = TribunalConstitucionalSource  # type: ignore[assignment]
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.inlabs import InlabsDOUSource
        source_map["inlabs"] = InlabsDOUSource  # type: ignore[assignment]
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.sidof import SidofDOFSource
        source_map["sidof"] = SidofDOFSource  # type: ignore[assignment]
    except ImportError:
        pass

    SourceClass = source_map.get(source_id)
    if SourceClass is None:
        raise ValueError(f"Unknown source: {source_id}")

    storage = _make_storage()

    async def _fetch() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=30, headers=_HEADERS, follow_redirects=True
        ) as http:
            src = SourceClass(http_client=http)  # type: ignore[call-arg]
            ids = doc_ids or await src.list_documents()
            fetched = skipped = errors = 0
            for doc_id in ids:
                try:
                    await src._rate_limiter.acquire()
                    raw = await src.fetch(doc_id)
                    result = storage.write_raw(raw)
                    if result.skipped:
                        skipped += 1
                    else:
                        fetched += 1
                except Exception as exc:
                    errors += 1
                    logger.error("raw_fetch_error", source=source_id, doc_id=doc_id, error=str(exc))
            return {"fetched": fetched, "skipped": skipped, "errors": errors, "total": len(ids)}

    return asyncio.run(_fetch())


# ---------------------------------------------------------------------------
# BOE
# ---------------------------------------------------------------------------

@asset(
    group_name="boe",
    compute_kind="scraper",
    description="Raw BOE XML documents downloaded from boe.es",
)
def boe_raw(context: AssetExecutionContext) -> Output[dict[str, Any]]:
    report = _run_source_fetch("boe")
    context.log.info(f"BOE raw: {report}")

    yield Output(
        value=report,
        data_version=DataVersion(str(report["fetched"] + report["skipped"])),
        metadata={
            "docs_fetched": report["fetched"],
            "docs_skipped": report["skipped"],
            "errors": report["errors"],
        },
    )


@asset_check(asset=boe_raw, name="boe_raw_has_documents")
def boe_raw_has_documents(context: AssetExecutionContext) -> AssetCheckResult:
    raw_dir = _DATA_DIR / "raw" / "boe"
    count = len(list(raw_dir.glob("*.xml"))) if raw_dir.exists() else 0
    return AssetCheckResult(passed=count > 0, metadata={"xml_count": count})


# ---------------------------------------------------------------------------
# EUR-Lex
# ---------------------------------------------------------------------------

@asset(
    group_name="eurlex",
    compute_kind="scraper",
    description="Raw EUR-Lex XML documents downloaded via Cellar API",
)
def eurlex_raw(context: AssetExecutionContext) -> Output[dict[str, Any]]:
    report = _run_source_fetch("eurlex")
    context.log.info(f"EUR-Lex raw: {report}")

    yield Output(
        value=report,
        data_version=DataVersion(str(report["fetched"] + report["skipped"])),
        metadata={
            "docs_fetched": report["fetched"],
            "docs_skipped": report["skipped"],
            "errors": report["errors"],
        },
    )


@asset_check(asset=eurlex_raw, name="eurlex_raw_has_documents")
def eurlex_raw_has_documents(context: AssetExecutionContext) -> AssetCheckResult:
    raw_dir = _DATA_DIR / "raw" / "eurlex"
    count = len(list(raw_dir.glob("*.xml"))) if raw_dir.exists() else 0
    return AssetCheckResult(passed=count > 0, metadata={"xml_count": count})


# ---------------------------------------------------------------------------
# New GREEN sources — generated with shared helper
# ---------------------------------------------------------------------------

def _make_raw_asset(src_id: str, group: str, description: str) -> Any:
    @asset(
        name=f"{src_id}_raw",
        group_name=group,
        compute_kind="scraper",
        description=description,
    )
    def _asset(context: AssetExecutionContext) -> Output[dict[str, Any]]:  # type: ignore[misc]
        try:
            report = _run_source_fetch(src_id)
        except (ValueError, ImportError) as exc:
            context.log.warning(f"{src_id} source not available: {exc}")
            report = {"fetched": 0, "skipped": 0, "errors": 1, "total": 0}

        yield Output(
            value=report,
            data_version=DataVersion(str(report["fetched"] + report["skipped"])),
            metadata={
                "docs_fetched": report["fetched"],
                "docs_skipped": report["skipped"],
                "errors": report["errors"],
            },
        )

    return _asset


aepd_raw = _make_raw_asset("aepd", "aepd", "AEPD resoluciones — buscador público AEPD")
edpb_raw = _make_raw_asset("edpb", "edpb", "EDPB guidelines and opinions (PDF/HTML)")
bde_raw = _make_raw_asset("bde", "bde", "BdE circulares y guías supervisoras")
eba_raw = _make_raw_asset("eba", "eba", "EBA Single Rulebook Q&As")
esma_raw = _make_raw_asset("esma", "esma", "ESMA Q&As")
legislation_uk_raw = _make_raw_asset(
    "legislation_uk", "legislation_uk", "legislation.gov.uk XML API — UK financial legislation"
)
fca_raw = _make_raw_asset("fca", "fca", "FCA Handbook — HTML scraping (partial coverage)")


# ---------------------------------------------------------------------------
# CENDOJ — jurisprudencia (manual trigger only, ADR 0025)
# ---------------------------------------------------------------------------

@asset(
    group_name="jurisprudencia",
    compute_kind="scraper",
    description="CENDOJ dev-mode fetch — manual trigger only (ADR 0025)",
)
def cendoj_raw(context: AssetExecutionContext) -> Output[dict[str, Any]]:
    # Check QuotaTracker suspension before attempting any fetch
    try:
        from lex_agents_ingest.quota import QuotaTracker
        if QuotaTracker().is_suspended():
            raise RuntimeError(
                "CENDOJ quota is suspended. See runbook: docs/runbooks/cendoj-quota.md"
            )
    except ImportError:
        logger.warning("cendoj_raw: QuotaTracker not available — skipping suspension check")

    try:
        report = _run_source_fetch("cendoj")
    except (ValueError, ImportError) as exc:
        context.log.warning(f"cendoj source not available: {exc}")
        report = {"fetched": 0, "skipped": 0, "errors": 1, "total": 0}

    context.log.info(f"CENDOJ raw: {report}")
    yield Output(
        value=report,
        data_version=DataVersion(str(report["fetched"] + report["skipped"])),
        metadata={
            "docs_fetched": report["fetched"],
            "docs_skipped": report["skipped"],
            "errors": report["errors"],
            "source": "cendoj",
        },
    )


@asset_check(asset=cendoj_raw, name="cendoj_raw_not_suspended")
def cendoj_raw_not_suspended(context: AssetExecutionContext) -> AssetCheckResult:
    try:
        from lex_agents_ingest.quota import QuotaTracker
        suspended = QuotaTracker().is_suspended()
    except ImportError:
        suspended = False
    return AssetCheckResult(
        passed=not suspended,
        metadata={"suspended": suspended},
    )


# ---------------------------------------------------------------------------
# TC (Tribunal Constitucional) — jurisprudencia
# ---------------------------------------------------------------------------

tc_raw = _make_raw_asset(
    "tc", "jurisprudencia", "Tribunal Constitucional jurisprudencia — CENDOJ-TC endpoint"
)


@asset_check(asset=tc_raw, name="tc_raw_has_documents")
def tc_raw_has_documents(context: AssetExecutionContext) -> AssetCheckResult:
    raw_dir = _DATA_DIR / "raw" / "tc"
    count = len(list(raw_dir.iterdir())) if raw_dir.exists() else 0
    return AssetCheckResult(passed=count > 0, metadata={"doc_count": count})


# ---------------------------------------------------------------------------
# INLABS DOU (Brazil) — latam_sources
# ---------------------------------------------------------------------------

@asset(
    group_name="latam_sources",
    compute_kind="scraper",
    description="INLABS DOU — Diário Oficial da União (Brazil) via INLABS API",
)
def inlabs_raw(context: AssetExecutionContext) -> Output[dict[str, Any]]:
    token = os.environ.get("INLABS_TOKEN")
    if not token:
        raise RuntimeError(
            "INLABS_TOKEN environment variable is not set. "
            "Set it to your INLABS API token before running this asset."
        )

    try:
        report = _run_source_fetch("inlabs")
    except (ValueError, ImportError) as exc:
        context.log.warning(f"inlabs source not available: {exc}")
        report = {"fetched": 0, "skipped": 0, "errors": 1, "total": 0}

    context.log.info(f"INLABS DOU raw: {report}")
    yield Output(
        value=report,
        data_version=DataVersion(str(report["fetched"] + report["skipped"])),
        metadata={
            "docs_fetched": report["fetched"],
            "docs_skipped": report["skipped"],
            "errors": report["errors"],
            "source": "inlabs",
        },
    )


@asset_check(asset=inlabs_raw, name="inlabs_raw_has_documents")
def inlabs_raw_has_documents(context: AssetExecutionContext) -> AssetCheckResult:
    raw_dir = _DATA_DIR / "raw" / "inlabs"
    count = len(list(raw_dir.iterdir())) if raw_dir.exists() else 0
    return AssetCheckResult(passed=count > 0, metadata={"doc_count": count})


# ---------------------------------------------------------------------------
# SIDOF DOF (Mexico) — latam_sources
# ---------------------------------------------------------------------------

sidof_raw = _make_raw_asset(
    "sidof", "latam_sources", "SIDOF DOF — Diario Oficial de la Federación (Mexico)"
)


@asset_check(asset=sidof_raw, name="sidof_raw_has_documents")
def sidof_raw_has_documents(context: AssetExecutionContext) -> AssetCheckResult:
    raw_dir = _DATA_DIR / "raw" / "sidof"
    count = len(list(raw_dir.iterdir())) if raw_dir.exists() else 0
    return AssetCheckResult(passed=count > 0, metadata={"doc_count": count})


# Exported for definitions.py
ALL_RAW_ASSETS = [
    boe_raw, eurlex_raw,
    aepd_raw, edpb_raw, bde_raw, eba_raw, esma_raw,
    legislation_uk_raw, fca_raw,
    cendoj_raw, tc_raw,
    inlabs_raw, sidof_raw,
]
ALL_RAW_CHECKS = [
    boe_raw_has_documents, eurlex_raw_has_documents,
    cendoj_raw_not_suspended, tc_raw_has_documents,
    inlabs_raw_has_documents, sidof_raw_has_documents,
]
