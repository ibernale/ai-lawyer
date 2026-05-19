"""Tenant management endpoints — /api/v1/admin/tenants (super-admin only)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, require_role
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin/tenants", tags=["admin", "tenants"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TenantOut(BaseModel):
    id: str
    name: str
    plan: str
    disabled: bool
    created_at: str
    updated_at: str


class CreateTenantRequest(BaseModel):
    id: str
    name: str
    plan: str = "standard"


class UpdateTenantRequest(BaseModel):
    name: str | None = None
    plan: str | None = None
    disabled: bool | None = None


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_tenant_store(db_path: str) -> Any:
    from lex_agents_admin.tenant_store import TenantStore
    return TenantStore(db_path=db_path)


def get_tenant_store(settings: Settings = Depends(get_settings)) -> Any:
    return _get_tenant_store(settings.consultation_db_path)


def require_super_admin(
    current_user: CurrentUser = Depends(require_role("admin")),
) -> CurrentUser:
    """Only admins in the 'default' tenant are super-admins."""
    if current_user.tenant_id != "default":
        raise HTTPException(
            status_code=403,
            detail="Only super-admins (default tenant) can manage tenants.",
        )
    return current_user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=TenantOut, status_code=201)
async def create_tenant(
    body: CreateTenantRequest,
    current_user: CurrentUser = Depends(require_super_admin),
    store: Any = Depends(get_tenant_store),
) -> TenantOut:
    """Create a new tenant (super-admin only)."""
    existing = await store.get(body.id)
    if existing is not None:
        raise HTTPException(status_code=409, detail={"code": "TENANT_EXISTS",
                                                      "message": f"Tenant '{body.id}' already exists."})
    tenant = await store.create(body.id, body.name, body.plan)
    logger.info("tenant_created_via_api", tenant_id=body.id, actor=current_user.username)
    return TenantOut(
        id=tenant.id, name=tenant.name, plan=tenant.plan,
        disabled=tenant.disabled, created_at=tenant.created_at, updated_at=tenant.updated_at,
    )


@router.get("", response_model=list[TenantOut])
async def list_tenants(
    current_user: CurrentUser = Depends(require_super_admin),
    store: Any = Depends(get_tenant_store),
) -> list[TenantOut]:
    """List all tenants (super-admin only)."""
    tenants = await store.list_all()
    return [
        TenantOut(id=t.id, name=t.name, plan=t.plan,
                  disabled=t.disabled, created_at=t.created_at, updated_at=t.updated_at)
        for t in tenants
    ]


@router.get("/{tenant_id}", response_model=TenantOut)
async def get_tenant(
    tenant_id: str,
    current_user: CurrentUser = Depends(require_super_admin),
    store: Any = Depends(get_tenant_store),
) -> TenantOut:
    """Get a tenant by ID (super-admin only)."""
    tenant = await store.get(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND",
                                                      "message": f"Tenant '{tenant_id}' not found."})
    return TenantOut(
        id=tenant.id, name=tenant.name, plan=tenant.plan,
        disabled=tenant.disabled, created_at=tenant.created_at, updated_at=tenant.updated_at,
    )


@router.patch("/{tenant_id}", response_model=TenantOut)
async def update_tenant(
    tenant_id: str,
    body: UpdateTenantRequest,
    current_user: CurrentUser = Depends(require_super_admin),
    store: Any = Depends(get_tenant_store),
) -> TenantOut:
    """Update tenant name, plan, or disabled status (super-admin only)."""
    if tenant_id == "default" and body.disabled is True:
        raise HTTPException(status_code=400, detail={"code": "CANNOT_DISABLE_DEFAULT",
                                                      "message": "Cannot disable the default tenant."})
    ok = await store.update(tenant_id, name=body.name, plan=body.plan, disabled=body.disabled)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND",
                                                      "message": f"Tenant '{tenant_id}' not found."})
    tenant = await store.get(tenant_id)
    assert tenant is not None
    logger.info("tenant_updated_via_api", tenant_id=tenant_id, actor=current_user.username)
    return TenantOut(
        id=tenant.id, name=tenant.name, plan=tenant.plan,
        disabled=tenant.disabled, created_at=tenant.created_at, updated_at=tenant.updated_at,
    )


@router.delete("/{tenant_id}", status_code=204)
async def disable_tenant(
    tenant_id: str,
    current_user: CurrentUser = Depends(require_super_admin),
    store: Any = Depends(get_tenant_store),
) -> None:
    """Soft-delete (disable) a tenant. Does not delete data."""
    if tenant_id == "default":
        raise HTTPException(status_code=400, detail={"code": "CANNOT_DISABLE_DEFAULT",
                                                      "message": "Cannot disable the default tenant."})
    ok = await store.disable(tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND",
                                                      "message": f"Tenant '{tenant_id}' not found."})
    logger.info("tenant_disabled_via_api", tenant_id=tenant_id, actor=current_user.username)
