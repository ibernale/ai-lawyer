"""Backwards-compatibility shim — re-exports QueryRouter from routing/router_v1."""

from __future__ import annotations

from lex_agents_agents.routing.router_v1 import QueryRouter

__all__ = ["QueryRouter"]
