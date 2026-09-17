"""Single-version endpoints.

The collection routes (`/resumes/{id}/versions`, `/resumes/{id}/restore`) live
in ``routers/resumes.py`` next to their siblings; this module owns everything
addressed by a bare ``version_id``.
"""

import logging

from fastapi import APIRouter, HTTPException

from app.database import DatabaseBusyError, db
from app.deps import WorkspaceId
from app.schemas.versions import VersionDetail, VersionUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/versions", tags=["Version History"])

_DELETE_CONFLICTS = {
    "is_head": "Cannot delete the current version. Restore another one first.",
    "is_pinned": "Cannot delete a pinned version. Unpin it first.",
}


@router.get("/{version_id}", response_model=VersionDetail)
async def get_version(version_id: str, workspace_id: WorkspaceId) -> VersionDetail:
    """Fetch one version, document included."""
    version = await db.get_resume_version(version_id, workspace_id=workspace_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return VersionDetail(**version)


@router.patch("/{version_id}", response_model=VersionDetail)
async def update_version(
    version_id: str, request: VersionUpdateRequest, workspace_id: WorkspaceId
) -> VersionDetail:
    """Label or pin a version. Its content never changes."""
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        version = await db.update_resume_version(
            version_id, updates, workspace_id=workspace_id
        )
    except DatabaseBusyError:
        raise
    except Exception as exc:
        logger.exception("Failed to update version %s", version_id)
        raise HTTPException(
            status_code=500, detail="Failed to update version. Please try again."
        ) from exc
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return VersionDetail(**version)


@router.delete("/{version_id}")
async def delete_version(version_id: str, workspace_id: WorkspaceId) -> dict[str, str]:
    """Delete a version. The current one and pinned ones are refused."""
    try:
        result = await db.delete_resume_version(version_id, workspace_id=workspace_id)
    except DatabaseBusyError:
        raise
    except Exception as exc:
        logger.exception("Failed to delete version %s", version_id)
        raise HTTPException(
            status_code=500, detail="Failed to delete version. Please try again."
        ) from exc

    if result["deleted"]:
        return {"message": "Version deleted"}
    if result["reason"] == "not_found":
        raise HTTPException(status_code=404, detail="Version not found")
    raise HTTPException(status_code=409, detail=_DELETE_CONFLICTS[result["reason"]])
