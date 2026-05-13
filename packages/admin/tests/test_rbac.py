"""Unit tests for RBAC helpers (role_gte + requires_role hierarchy)."""

from __future__ import annotations

import pytest
from lex_agents_admin.rbac import Role, role_gte


class TestRoleGte:
    def test_same_role(self) -> None:
        for role in Role:
            assert role_gte(role.value, role)

    def test_admin_satisfies_operator(self) -> None:
        assert role_gte(Role.ADMIN, Role.OPERATOR)

    def test_admin_satisfies_analyst(self) -> None:
        assert role_gte(Role.ADMIN, Role.ANALYST)

    def test_operator_does_not_satisfy_admin(self) -> None:
        assert not role_gte(Role.OPERATOR, Role.ADMIN)

    def test_analyst_does_not_satisfy_operator(self) -> None:
        assert not role_gte(Role.ANALYST, Role.OPERATOR)

    def test_unknown_role_returns_false(self) -> None:
        assert not role_gte("ghost", Role.ANALYST)
