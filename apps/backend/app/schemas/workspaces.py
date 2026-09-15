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
    content_language: str = Field(default="en", min_length=2, max_length=10)


class WorkspaceUpdateRequest(BaseModel):
    """Partial workspace update; omitted fields are left untouched."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    content_language: str | None = Field(default=None, min_length=2, max_length=10)
    is_default: bool | None = None
