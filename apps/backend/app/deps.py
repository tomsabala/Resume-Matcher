"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends

from app.tenancy import ActiveTenant, active_tenant


async def resolve_workspace_id() -> str:
    """The workspace this request acts on, as resolved by ``TenantMiddleware``.

    A pure read of the request's tenant. The header parsing, the
    ``X-Workspace-Id`` ownership check and the tolerant fallback to the
    tenant's own default all happen once, in middleware, so that the
    synchronous config and API-key paths — which have no ``Request`` — see the
    same answer as the endpoints.
    """
    return active_tenant().workspace_id


WorkspaceId = Annotated[str, Depends(resolve_workspace_id)]

#: For the tenant-level endpoints (``/workspaces``), which act on the identity
#: rather than on one of its profiles.
ActiveTenantDep = Annotated[ActiveTenant, Depends(active_tenant)]
