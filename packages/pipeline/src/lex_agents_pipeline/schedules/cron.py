"""
Cron schedules — one ScheduleDefinition per GREEN source.

Schedule table
--------------
BOE                : daily      07:00 UTC
EUR-Lex            : weekly     Mon 06:00 UTC
AEPD               : weekly     Fri 06:00 UTC
EDPB               : weekly     Mon 06:00 UTC
BdE                : daily      07:30 UTC
EBA Q&As           : weekly     Tue 06:00 UTC
ESMA Q&As          : weekly     Tue 06:00 UTC
legislation.gov.uk : weekly     Wed 06:00 UTC
FCA Handbook       : weekly     Wed 06:00 UTC

Each schedule targets the corresponding per-source ingest job from
`lex_agents_pipeline.jobs.ingest_jobs`.  If that module does not exist yet the
schedules fall back to a no-op stub so this module can be imported safely in
any phase of development.
"""

from __future__ import annotations

import logging
from typing import Any

from dagster import DefaultScheduleStatus, ScheduleDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports from ingest_jobs — won't fail if the file doesn't exist yet
# ---------------------------------------------------------------------------


def _load_job(name: str) -> Any:
    """Return the named job from ingest_jobs, or None if unavailable."""
    try:
        import importlib
        module = importlib.import_module("lex_agents_pipeline.jobs.ingest_jobs")
        return getattr(module, name, None)
    except ImportError:
        return None


def _job_or_stub(name: str) -> Any:
    """Return job by name; fall back to a trivial no-op job stub."""
    job = _load_job(name)
    if job is not None:
        return job

    logger.warning(
        "schedules: job '%s' not found in ingest_jobs — schedule will produce no runs", name
    )
    return None


# ---------------------------------------------------------------------------
# Helper: build a ScheduleDefinition, skipping gracefully if job is absent
# ---------------------------------------------------------------------------


def _make_schedule(
    *,
    name: str,
    job_name: str,
    cron_schedule: str,
    description: str,
    run_config: dict[str, Any] | None = None,
) -> ScheduleDefinition:
    job = _job_or_stub(job_name)

    if job is not None:
        return ScheduleDefinition(
            name=name,
            job=job,
            cron_schedule=cron_schedule,
            description=description,
            default_status=DefaultScheduleStatus.RUNNING,
            run_config=run_config or {},
        )

    # Job stub: create a schedule that references the job by name only.
    # Dagster will resolve it at repository load time; if the job is still
    # absent it will show an error in the UI rather than crashing the process.
    return ScheduleDefinition(
        name=name,
        job_name=job_name,
        cron_schedule=cron_schedule,
        description=description,
        default_status=DefaultScheduleStatus.STOPPED,  # safe default for stub
        run_config=run_config or {},
    )


# ---------------------------------------------------------------------------
# BOE — daily 07:00 UTC
# ---------------------------------------------------------------------------

boe_daily_schedule = _make_schedule(
    name="boe_daily_ingest",
    job_name="boe_ingest_job",
    cron_schedule="0 7 * * *",
    description="Daily ingestion of BOE (Boletín Oficial del Estado) publications at 07:00 UTC.",
    run_config={"ops": {"boe_raw": {"config": {"use_fixtures": False}}}},
)

# ---------------------------------------------------------------------------
# EUR-Lex — weekly Monday 06:00 UTC
# ---------------------------------------------------------------------------

eur_lex_weekly_schedule = _make_schedule(
    name="eur_lex_weekly_ingest",
    job_name="eur_lex_ingest_job",
    cron_schedule="0 6 * * 1",
    description="Weekly ingestion of EUR-Lex legislation on Mondays at 06:00 UTC.",
)

# ---------------------------------------------------------------------------
# AEPD — weekly Friday 06:00 UTC
# ---------------------------------------------------------------------------

aepd_weekly_schedule = _make_schedule(
    name="aepd_weekly_ingest",
    job_name="aepd_ingest_job",
    cron_schedule="0 6 * * 5",
    description="Weekly ingestion of AEPD (Agencia Española de Protección de Datos) on Fridays at 06:00 UTC.",
)

# ---------------------------------------------------------------------------
# EDPB — weekly Monday 06:00 UTC
# ---------------------------------------------------------------------------

edpb_weekly_schedule = _make_schedule(
    name="edpb_weekly_ingest",
    job_name="edpb_ingest_job",
    cron_schedule="0 6 * * 1",
    description="Weekly ingestion of EDPB guidelines and recommendations on Mondays at 06:00 UTC.",
)

# ---------------------------------------------------------------------------
# BdE — daily 07:30 UTC
# ---------------------------------------------------------------------------

bde_daily_schedule = _make_schedule(
    name="bde_daily_ingest",
    job_name="bde_ingest_job",
    cron_schedule="30 7 * * *",
    description="Daily ingestion of Banco de España regulatory publications at 07:30 UTC.",
)

# ---------------------------------------------------------------------------
# EBA Q&As — weekly Tuesday 06:00 UTC
# ---------------------------------------------------------------------------

eba_qa_weekly_schedule = _make_schedule(
    name="eba_qa_weekly_ingest",
    job_name="eba_qa_ingest_job",
    cron_schedule="0 6 * * 2",
    description="Weekly ingestion of EBA Q&A database on Tuesdays at 06:00 UTC.",
)

# ---------------------------------------------------------------------------
# ESMA Q&As — weekly Tuesday 06:00 UTC
# ---------------------------------------------------------------------------

esma_qa_weekly_schedule = _make_schedule(
    name="esma_qa_weekly_ingest",
    job_name="esma_qa_ingest_job",
    cron_schedule="0 6 * * 2",
    description="Weekly ingestion of ESMA Q&A database on Tuesdays at 06:00 UTC.",
)

# ---------------------------------------------------------------------------
# legislation.gov.uk — weekly Wednesday 06:00 UTC
# ---------------------------------------------------------------------------

legislation_gov_uk_weekly_schedule = _make_schedule(
    name="legislation_gov_uk_weekly_ingest",
    job_name="legislation_gov_uk_ingest_job",
    cron_schedule="0 6 * * 3",
    description="Weekly ingestion of legislation.gov.uk publications on Wednesdays at 06:00 UTC.",
)

# ---------------------------------------------------------------------------
# FCA Handbook — weekly Wednesday 06:00 UTC
# ---------------------------------------------------------------------------

fca_handbook_weekly_schedule = _make_schedule(
    name="fca_handbook_weekly_ingest",
    job_name="fca_handbook_ingest_job",
    cron_schedule="0 6 * * 3",
    description="Weekly ingestion of FCA Handbook updates on Wednesdays at 06:00 UTC.",
)

# ---------------------------------------------------------------------------
# FinOps cost sync — daily 06:00 UTC
# ---------------------------------------------------------------------------

cost_sync_schedule = ScheduleDefinition(
    job_name="finops_cost_sync_job",
    cron_schedule="0 6 * * *",  # 06:00 UTC daily
    default_status=DefaultScheduleStatus.RUNNING,
)

# ---------------------------------------------------------------------------
# Exported list — add to Definitions in definitions.py
# ---------------------------------------------------------------------------

all_schedules = [
    boe_daily_schedule,
    eur_lex_weekly_schedule,
    aepd_weekly_schedule,
    edpb_weekly_schedule,
    bde_daily_schedule,
    eba_qa_weekly_schedule,
    esma_qa_weekly_schedule,
    legislation_gov_uk_weekly_schedule,
    fca_handbook_weekly_schedule,
    cost_sync_schedule,
]

# Alias used by definitions.py lazy import
ALL_SCHEDULES = all_schedules
