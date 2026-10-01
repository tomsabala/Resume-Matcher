"""Pydantic schemas for the workspace API."""

from pydantic import BaseModel, Field


class WorkspaceResponse(BaseModel):
    """One workspace as returned by the API."""

    workspace_id: str
    name: str
    slug: str
    content_language: str
    is_default: bool
    created_at: str
    updated_at: str


class WorkspaceListResponse(BaseModel):
    """All workspaces, oldest first."""

    workspaces: list[WorkspaceResponse]


class WorkspaceCreateRequest(BaseModel):
    """Create a workspace. The slug is derived server-side from ``name``."""

    name: str = Field(min_length=1, max_length=80)


class WorkspaceUpdateRequest(BaseModel):
    """Partial workspace update; omitted fields are left untouched."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_default: bool | None = None
    #: Supported content languages. A third one is one row here, one in
    #: ``LANGUAGE_NAMES``, and (if RTL) one in ``RTL_CONTENT_LANGUAGES``.
    content_language: str | None = Field(default=None, pattern="^(en|he)$")
