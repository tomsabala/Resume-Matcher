"""Workspace management endpoints.

A workspace is a named owner profile ("Tom", "Lior — Hebrew") that scopes
resumes, job descriptions and tracker cards. Each tenant owns its own set of
them: identity arrives as ``X-Apps-Tenant`` from the gateway and is resolved
once by ``TenantMiddleware``, so these endpoints are tenant-level — they act on
the caller's own profiles, never on the whole table. ``X-Workspace-Id`` selects
which of those profiles a request acts on, and is honoured only when it names
one of them.
"""

import logging

from fastapi import APIRouter, HTTPException

from app.database import DatabaseBusyError, db
from app.deps import ActiveTenantDep
from app.schemas.workspaces import (
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])

_DELETE_CONFLICTS = {
    "is_default": "Cannot delete the default workspace. Make another one default first.",
    "last_workspace": "Cannot delete the only workspace.",
}


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(tenant: ActiveTenantDep) -> WorkspaceListResponse:
    """List the caller's workspaces, oldest first."""
    workspaces = await db.workspaces_for_tenant(tenant.tenant_ref)
    return WorkspaceListResponse(
        workspaces=[WorkspaceResponse(**row) for row in workspaces]
    )


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    request: WorkspaceCreateRequest, tenant: ActiveTenantDep
) -> WorkspaceResponse:
    """Create a workspace; its slug is derived from the name and de-duplicated."""
    try:
        workspace = await db.create_workspace(
            name=request.name.strip(),
            content_language=request.content_language,
            tenant_ref=tenant.tenant_ref,
            is_anonymous=tenant.is_anonymous,
        )
    except DatabaseBusyError:
        raise
    except Exception as exc:
        logger.exception("Failed to create workspace")
        raise HTTPException(
            status_code=500, detail="Failed to create workspace. Please try again."
        ) from exc
    return WorkspaceResponse(**workspace)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str, request: WorkspaceUpdateRequest, tenant: ActiveTenantDep
) -> WorkspaceResponse:
    """Rename a workspace, change its content language, or make it the default."""
    # The id comes from the path rather than from the resolved tenant, so
    # without this another tenant's profile would be renamable by anyone who
    # learns its id.
    if workspace_id not in tenant.workspace_ids:
        raise HTTPException(status_code=404, detail="Workspace not found")
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    if updates.get("is_default") is False:
        # Unsetting the default would leave the app with no fallback; promote
        # another workspace instead.
        raise HTTPException(
            status_code=400,
            detail="Set another workspace as default instead of unsetting this one.",
        )
    try:
        workspace = await db.update_workspace(workspace_id, updates)
    except DatabaseBusyError:
        raise
    except Exception as exc:
        logger.exception("Failed to update workspace %s", workspace_id)
        raise HTTPException(
            status_code=500, detail="Failed to update workspace. Please try again."
        ) from exc
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspaceResponse(**workspace)


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str, tenant: ActiveTenantDep
) -> dict[str, str]:
    """Delete a workspace and everything scoped to it."""
    if workspace_id not in tenant.workspace_ids:
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        result = await db.delete_workspace(workspace_id)
    except DatabaseBusyError:
        raise
    except Exception as exc:
        logger.exception("Failed to delete workspace %s", workspace_id)
        raise HTTPException(
            status_code=500, detail="Failed to delete workspace. Please try again."
        ) from exc

    if result["deleted"]:
        return {"message": "Workspace deleted"}
    if result["reason"] == "not_found":
        raise HTTPException(status_code=404, detail="Workspace not found")
    raise HTTPException(status_code=409, detail=_DELETE_CONFLICTS[result["reason"]])
