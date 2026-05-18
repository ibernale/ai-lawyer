"""FeedbackProcessor — cierra el loop entre feedback negativo y cola de auditoría."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from lex_agents_audit.audit_store import AuditSampleRecord, AuditStore

from lex_agents_api.db import ConsultationStore

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_NEGATIVE_VERDICTS = frozenset({"dudoso", "incorrecto"})


class FeedbackProcessor:
    """Enqueues an audit sample whenever a user submits a negative verdict."""

    async def process(
        self,
        trace_id: str,
        verdict: str,
        notes: str | None,
        *,
        reviewer_username: str,
        consultation_store: ConsultationStore,
        audit_store: AuditStore,
    ) -> bool:
        """Process a feedback verdict and create an audit sample if warranted.

        Returns True when a new AuditSample was created, False otherwise.
        """
        if verdict not in _NEGATIVE_VERDICTS:
            return False

        consultation = await consultation_store.get(trace_id)
        if consultation is None:
            logger.warning(
                "feedback_processor_consultation_not_found",
                trace_id=trace_id,
                verdict=verdict,
                reviewer=reviewer_username,
            )
            return False

        existing = await audit_store.find_by_trace_id(trace_id)
        if existing is not None:
            logger.debug(
                "feedback_processor_audit_sample_already_exists",
                trace_id=trace_id,
                existing_id=existing.id,
            )
            return False

        record = AuditSampleRecord(
            trace_id=trace_id,
            query=consultation.query,
            response_json=consultation.response_json,
            branch=consultation.branch or "",
            depth=consultation.depth_used or "",
            sampled_at=datetime.now(UTC),
            status="pending",
        )
        await audit_store.save(record)

        logger.info(
            "feedback_auto_sampled",
            trace_id=trace_id,
            verdict=verdict,
            reviewer=reviewer_username,
        )
        return True
