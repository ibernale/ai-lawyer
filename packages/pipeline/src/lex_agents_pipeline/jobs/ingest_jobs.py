"""Dagster job definitions — one per source, composing the full asset graph."""

from __future__ import annotations

from dagster import AssetSelection, define_asset_job

# Per-source full pipeline jobs (raw → indexed)
ingest_boe_job = define_asset_job(
    name="ingest_boe_job",
    selection=AssetSelection.groups("boe"),
    description="Full BOE ingestion: download → parse → chunk → contextualise → embed → index",
)

ingest_eurlex_job = define_asset_job(
    name="ingest_eurlex_job",
    selection=AssetSelection.groups("eurlex"),
    description="Full EUR-Lex ingestion",
)

ingest_aepd_job = define_asset_job(
    name="ingest_aepd_job",
    selection=AssetSelection.groups("aepd"),
    description="AEPD resoluciones ingestion",
)

ingest_edpb_job = define_asset_job(
    name="ingest_edpb_job",
    selection=AssetSelection.groups("edpb"),
    description="EDPB guidelines and opinions ingestion",
)

ingest_bde_job = define_asset_job(
    name="ingest_bde_job",
    selection=AssetSelection.groups("bde"),
    description="BdE circulares ingestion",
)

ingest_eba_job = define_asset_job(
    name="ingest_eba_job",
    selection=AssetSelection.groups("eba"),
    description="EBA Single Rulebook Q&As ingestion",
)

ingest_esma_job = define_asset_job(
    name="ingest_esma_job",
    selection=AssetSelection.groups("esma"),
    description="ESMA Q&As ingestion",
)

ingest_legislation_uk_job = define_asset_job(
    name="ingest_legislation_uk_job",
    selection=AssetSelection.groups("legislation_uk"),
    description="legislation.gov.uk UK financial legislation ingestion",
)

ingest_fca_job = define_asset_job(
    name="ingest_fca_job",
    selection=AssetSelection.groups("fca"),
    description="FCA Handbook ingestion (partial coverage)",
)

# Re-index without re-fetching (for model/prompt changes)
reindex_all_job = define_asset_job(
    name="reindex_all_job",
    selection=AssetSelection.assets(
        "boe_contextualized", "eurlex_contextualized",
        "aepd_contextualized", "edpb_contextualized", "bde_contextualized",
        "eba_contextualized", "esma_contextualized",
        "legislation_uk_contextualized", "fca_contextualized",
    ).downstream(),
    description="Re-embed and re-index all documents without re-fetching raw (for model changes)",
)

# FinOps cost sync + reconciliation
finops_cost_sync_job = define_asset_job(
    "finops_cost_sync_job",
    selection=AssetSelection.groups("finops"),
    description="Fetch Anthropic hourly usage/cost data and reconcile against local estimates",
)

# Convenience: all sources at once
ingest_all_job = define_asset_job(
    name="ingest_all_job",
    selection=AssetSelection.groups(
        "boe", "eurlex", "aepd", "edpb", "bde", "eba", "esma", "legislation_uk", "fca"
    ),
    description="Run all GREEN source ingestion pipelines",
)

ALL_JOBS = [
    ingest_boe_job, ingest_eurlex_job,
    ingest_aepd_job, ingest_edpb_job, ingest_bde_job,
    ingest_eba_job, ingest_esma_job,
    ingest_legislation_uk_job, ingest_fca_job,
    ingest_all_job, reindex_all_job,
    finops_cost_sync_job,
]
