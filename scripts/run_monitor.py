#!/usr/bin/env python3
"""Run a regulation change monitor scan across all configured sources.

Usage:
    uv run python scripts/run_monitor.py [--db PATH] [--report PATH] [--sources SRC1,SRC2]

Exit codes:
    0 — scan completed (may have found 0 new events)
    1 — unhandled error
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure the repo root is on sys.path (needed when run outside a package install).
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "packages" / "ingest" / "src"))

import structlog  # noqa: E402
from lex_agents_ingest.change_monitor import ChangeEventStore, ChangeMonitor  # noqa: E402

logger: structlog.BoundLogger = structlog.get_logger(__name__)


def _build_sources(source_ids: list[str] | None):  # type: ignore[return]
    """Import and instantiate sources by ID."""
    from lex_agents_ingest.sources.bcb_brasil import BcbBrasilSource
    from lex_agents_ingest.sources.bcbs_bis import BcbsBisSource
    from lex_agents_ingest.sources.bcra import BcraSource
    from lex_agents_ingest.sources.boe import BoeSource
    from lex_agents_ingest.sources.cnmc import CnmcSource
    from lex_agents_ingest.sources.eurlex import EurlexSource
    from lex_agents_ingest.sources.federal_register import FederalRegisterSource
    from lex_agents_ingest.sources.sepblac import SepblacSource

    all_sources = {
        "boe": BoeSource,
        "eurlex": EurlexSource,
        "bcbs_bis": BcbsBisSource,
        "sepblac": SepblacSource,
        "cnmc": CnmcSource,
        "federal_register": FederalRegisterSource,
        "bcb_brasil": BcbBrasilSource,
        "bcra": BcraSource,
    }

    if source_ids:
        selected = {k: v for k, v in all_sources.items() if k in source_ids}
        unknown = set(source_ids) - set(all_sources)
        if unknown:
            logger.warning("unknown_sources_ignored", unknown=sorted(unknown))
    else:
        selected = all_sources

    return [cls() for cls in selected.values()]


async def _run(db_path: str, report_path: str | None, source_ids: list[str] | None) -> int:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    store = ChangeEventStore(db_path)
    await store.init()

    sources = _build_sources(source_ids)
    if not sources:
        logger.error("no_sources_to_scan")
        return 1

    monitor = ChangeMonitor(sources, store)
    new_events = await monitor.scan()

    logger.info("scan_complete", n_new=len(new_events), n_sources=len(sources))

    # Write JSON report
    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        report = {
            "n_new": len(new_events),
            "n_sources": len(sources),
            "events": [
                {
                    "id": e.id,
                    "source_id": e.source_id,
                    "document_id": e.document_id,
                    "title": e.title,
                    "severity": e.severity,
                    "domain": e.domain,
                    "detected_at": e.detected_at.isoformat(),
                }
                for e in new_events
            ],
        }
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        logger.info("report_written", path=report_path)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Regulation change monitor scan")
    parser.add_argument(
        "--db", default="data/monitor.db", help="Path to the SQLite monitor database"
    )
    parser.add_argument(
        "--report", default=None, help="Path to write the JSON scan report"
    )
    parser.add_argument(
        "--sources",
        default=None,
        help="Comma-separated source IDs to scan (default: all)",
    )
    args = parser.parse_args()

    source_ids = [s.strip() for s in args.sources.split(",")] if args.sources else None

    exit_code = asyncio.run(_run(args.db, args.report, source_ids))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
