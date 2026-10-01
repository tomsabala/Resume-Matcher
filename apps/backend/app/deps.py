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


async def resolve_content_language() -> str:
    """The language this workspace's generated content is written in.

    A default, not a verdict: each generated artifact detects its own language
    from the text it is generated from (``app.services.language``) and falls
    back to this only when that text is too short to judge.
    """
    # Imported here, not at module scope: app.database imports app.deps.
    from app.database import db

    workspace = await db.get_workspace(active_tenant().workspace_id)
    return (workspace or {}).get("content_language") or "en"


ContentLanguage = Annotated[str, Depends(resolve_content_language)]
