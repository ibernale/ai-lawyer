"""Dagster partition definitions for the ingestion pipeline."""

from __future__ import annotations

from dagster import DailyPartitionsDefinition, WeeklyPartitionsDefinition

# BOE publishes daily (working days); partition by date
boe_daily_partitions = DailyPartitionsDefinition(
    start_date="2024-01-01",
    timezone="Europe/Madrid",
)

# EUR-Lex updates are batch-checked weekly
eurlex_weekly_partitions = WeeklyPartitionsDefinition(
    start_date="2024-01-01",
    timezone="Europe/Madrid",
)

# Other sources — weekly is sufficient
weekly_partitions = WeeklyPartitionsDefinition(
    start_date="2024-01-01",
    timezone="Europe/Madrid",
)
