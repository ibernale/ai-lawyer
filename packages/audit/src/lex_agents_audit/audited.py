"""@audited decorator for wrapping async admin actions with audit trail logging."""

from __future__ import annotations

import functools
from typing import Any, Callable

import structlog

from lex_agents_audit.audit_trail import get_audit_trail_manager

logger: structlog.BoundLogger = structlog.get_logger(__name__)


def audited(action_type: str, target_type: str) -> Callable[[Any], Any]:
    """Decorator that logs an action to the audit trail.

    The decorated function must accept `reason: str` and `actor_username: str`
    and `actor_role: str` as keyword arguments.  The function may optionally
    return a dict with keys ``before`` and ``after`` to capture state change;
    otherwise both are recorded as None.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(
            *args: Any,
            reason: str,
            actor_username: str,
            actor_role: str,
            target_id: str | None = None,
            correlation_id: str | None = None,
            **kwargs: Any,
        ) -> Any:
            if not reason.strip():
                raise ValueError("reason must not be empty for audited actions")

            result = await fn(
                *args,
                reason=reason,
                actor_username=actor_username,
                actor_role=actor_role,
                target_id=target_id,
                correlation_id=correlation_id,
                **kwargs,
            )

            before: Any = None
            after: Any = None
            if isinstance(result, dict) and ("before" in result or "after" in result):
                before = result.get("before")
                after = result.get("after")

            mgr = get_audit_trail_manager()
            if mgr is not None:
                try:
                    await mgr.log(
                        action_type=action_type,
                        target_type=target_type,
                        actor=actor_username,
                        actor_role=actor_role,
                        reason=reason,
                        target_id=target_id,
                        before=before,
                        after=after,
                        correlation_id=correlation_id,
                    )
                except Exception as exc:
                    logger.warning("audited_log_failed", action_type=action_type, error=str(exc))
            else:
                logger.warning("audited_no_manager", action_type=action_type)

            return result

        return wrapper

    return decorator
