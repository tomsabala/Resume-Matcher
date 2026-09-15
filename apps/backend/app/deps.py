"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, Header

from app.database import db


async def resolve_workspace_id(
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> str:
    """Resolve the active workspace for a request.

    Header first, default workspace otherwise. An *unknown* id also falls back
    rather than 404-ing: the header is client state (localStorage) that can
    outlive a deleted workspace, and the Playwright print route is fetched by
    Chromium without app headers at all.
    """
    if x_workspace_id:
        workspace = await db.get_workspace(x_workspace_id)
        if workspace is not None:
            return str(workspace["workspace_id"])
    return await db.default_workspace_id()


WorkspaceId = Annotated[str, Depends(resolve_workspace_id)]
