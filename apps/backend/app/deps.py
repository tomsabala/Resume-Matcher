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

    One ``get_workspace`` read per request: FastAPI caches a dependency's
    result, so an endpoint injecting both this and ``OutputLanguage`` pays for
    it once.
    """
    # Imported here, not at module scope: app.database imports app.deps.
    from app.database import db

    workspace = await db.get_workspace(active_tenant().workspace_id)
    return (workspace or {}).get("content_language") or "en"


ContentLanguage = Annotated[str, Depends(resolve_content_language)]


async def resolve_output_language(content_language: ContentLanguage) -> str:
    """The language name prompts interpolate into ``{output_language}``."""
    from app.prompts import get_language_name

    return get_language_name(content_language)


OutputLanguage = Annotated[str, Depends(resolve_output_language)]
